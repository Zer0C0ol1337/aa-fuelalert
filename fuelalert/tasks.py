"""Celery tasks for aa-fuelalert. Periodic scheduling is done in local.py (see README)."""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass

from celery import shared_task

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from allianceauth.services.hooks import get_extension_logger
from allianceauth.services.tasks import QueueOnce

from corptools.models import Starbase, Structure

from .app_settings import (
    FUELALERT_ALERT_OFFLINE,
    FUELALERT_IGNORE_STATES,
    FUELALERT_POS_ENABLED,
    FUELALERT_POS_IGNORE_STATES,
    FUELALERT_REARM_MARGIN_HOURS,
    FUELALERT_SEND_DELAY_SECONDS,
    FUELALERT_THRESHOLDS_HOURS,
)
from .core import evaluate_structure, format_remaining
from .helpers import estimate_starbases, visible_corp_audits
from .models import AlertLog, Recipient
from .messaging import MessageError, MessageTemporaryError, send_to_recipient

logger = get_extension_logger(__name__)

MAX_LINES_PER_MESSAGE = 15


@dataclass
class Watched:
    """One structure or POS as the fuel check sees it."""

    item_id: int
    corporation_id: int
    label: str
    fuel_expires: dt.datetime | None  # None = no fuel / offline
    is_pos: bool = False


def _label(corp, name, system, fallback) -> str:
    """Short label for a message: [TICKER] Name (System)."""
    ticker = corp.corporation_ticker
    name = name or fallback
    if system and not name.startswith(system):
        return f"[{ticker}] {name} ({system})"
    return f"[{ticker}] {name}"


def _watched_structures() -> list[Watched]:
    """All Upwell structures from Corptools that are not being anchored/unanchored."""
    structures = Structure.objects.exclude(state__in=FUELALERT_IGNORE_STATES).select_related(
        "corporation__corporation", "system_name"
    )
    return [
        Watched(
            item_id=s.structure_id,
            corporation_id=s.corporation.corporation.corporation_id,
            label=_label(
                s.corporation.corporation,
                s.name,
                s.system_name.name if s.system_name else "",
                str(s.structure_id),
            ),
            fuel_expires=s.fuel_expires,
        )
        for s in structures
    ]


def _watched_starbases() -> list[Watched]:
    """All POS from Corptools with a calculated fuel end time; offline towers count as empty."""
    starbases = Starbase.objects.exclude(state__in=FUELALERT_POS_IGNORE_STATES).select_related(
        "corporation__corporation__alliance", "system", "moon", "type_name"
    )
    result = []
    for starbase, pos in estimate_starbases(starbases):
        system = starbase.system.name if starbase.system else ""
        fallback = starbase.moon.name if starbase.moon else (
            starbase.type_name.name if starbase.type_name else str(starbase.starbase_id)
        )
        result.append(
            Watched(
                item_id=starbase.starbase_id,
                corporation_id=starbase.corporation.corporation.corporation_id,
                label="POS " + _label(starbase.corporation.corporation, starbase.name, system, fallback),
                fuel_expires=None if starbase.state == "offline" else pos.fuel_expires,
                is_pos=True,
            )
        )
    return result


def _alert_line(item: Watched, decision, now) -> str:
    """One message line for a structure or POS that needs attention."""
    if decision.alert_kind == "offline":
        what = "POS OFFLINE / OUT OF FUEL" if item.is_pos else "OUT OF FUEL - services offline / low power"
        return f"⛔ {item.label}\n    {what}"
    icon = "🔴" if decision.alert_hours <= 24 else "🟠"
    expires = item.fuel_expires.strftime("%d.%m. %H:%M")
    remaining = format_remaining(item.fuel_expires, now)
    estimated = " (calculated)" if item.is_pos else ""
    return f"{icon} {item.label}\n    Fuel left: {remaining} (until {expires} EVE){estimated}"


def _build_message(lines: list[str]) -> str:
    """Full message text with header; long lists are cut to keep the message readable."""
    site = getattr(settings, "SITE_NAME", "Alliance Auth")
    shown = lines[:MAX_LINES_PER_MESSAGE]
    text = f"⛽ *Fuel Alert* - {site}\n\n" + "\n".join(shown)
    if len(lines) > len(shown):
        text += f"\n\n... and {len(lines) - len(shown)} more, see Fuel Alert in Auth."
    return text


@shared_task(base=QueueOnce)
def check_fuel_levels():
    """Check all Corptools structures and POS against the fuel thresholds and queue alerts."""
    now = timezone.now()
    existing = defaultdict(set)
    for item_id, key in AlertLog.objects.values_list("structure_id", "key"):
        existing[item_id].add(key)

    items = _watched_structures()
    if FUELALERT_POS_ENABLED:
        items += _watched_starbases()
    # Most urgent first, so messages list them in that order
    items.sort(key=lambda i: (i.fuel_expires is not None, i.fuel_expires or now))

    alerts_by_corp = defaultdict(list)
    seen_ids = set()
    to_create = []
    to_delete = Q()
    for item in items:
        if item.item_id in seen_ids:
            continue
        seen_ids.add(item.item_id)
        decision = evaluate_structure(
            fuel_expires=item.fuel_expires,
            now=now,
            thresholds=FUELALERT_THRESHOLDS_HOURS,
            existing_keys=existing.get(item.item_id, set()),
            alert_offline=FUELALERT_ALERT_OFFLINE,
            rearm_margin_hours=FUELALERT_REARM_MARGIN_HOURS,
        )
        to_create += [
            AlertLog(structure_id=item.item_id, key=key, fuel_expires=item.fuel_expires)
            for key in decision.add_keys
        ]
        for key in decision.remove_keys:
            to_delete |= Q(structure_id=item.item_id, key=key)
        if decision.alert_kind:
            alerts_by_corp[item.corporation_id].append(_alert_line(item, decision, now))

    with transaction.atomic():
        if to_delete:
            AlertLog.objects.filter(to_delete).delete()
        # Logs of structures/POS that no longer exist (or are ignored) are dropped
        stale_ids = set(existing) - seen_ids
        if stale_ids:
            AlertLog.objects.filter(structure_id__in=stale_ids).delete()
        AlertLog.objects.bulk_create(to_create, ignore_conflicts=True)

    logger.info(
        "Fuel check: %d structures/POS, %d corporations with new alerts",
        len(seen_ids),
        len(alerts_by_corp),
    )
    if alerts_by_corp:
        _dispatch(dict(alerts_by_corp))


def _dispatch(alerts_by_corp: dict) -> None:
    """Queue one combined message per recipient for the corps they follow and may see."""
    recipients = (
        Recipient.objects.filter(enabled=True, user__is_active=True)
        .select_related("user")
        .prefetch_related("corporations")
    )
    countdown = 0
    for recipient in recipients:
        # Permissions are checked at send time, so removed members stop getting alerts
        if not recipient.user.has_perm("fuelalert.basic_access"):
            continue
        wanted = {
            corp.corporation_id for corp in recipient.corporations.all()
        } & alerts_by_corp.keys()
        if not wanted:
            continue
        visible = visible_corp_audits(recipient.user).filter(
            corporation__corporation_id__in=wanted
        )
        corp_ids = sorted(visible.values_list("corporation__corporation_id", flat=True))
        lines = [line for corp_id in corp_ids for line in alerts_by_corp[corp_id]]
        if not lines:
            continue
        send_message.apply_async(
            args=[recipient.pk, _build_message(lines)], countdown=countdown
        )
        countdown += FUELALERT_SEND_DELAY_SECONDS


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def send_message(self, recipient_pk: int, text: str):
    """Send one message over the recipient's channel; network errors are retried up to 3 times."""
    try:
        recipient = Recipient.objects.get(pk=recipient_pk, enabled=True)
    except Recipient.DoesNotExist:
        return
    try:
        send_to_recipient(recipient, text)
    except MessageTemporaryError as ex:
        logger.warning(
            "%s message to recipient %s failed (%s), retrying",
            recipient.channel, recipient_pk, ex,
        )
        raise self.retry() from None
    except MessageError as ex:
        logger.warning(
            "%s message to recipient %s rejected: %s", recipient.channel, recipient_pk, ex
        )
        return
    logger.info("%s message sent to recipient %s", recipient.channel, recipient_pk)
