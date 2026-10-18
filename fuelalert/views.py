"""Views for aa-fuelalert."""

import datetime as dt

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from allianceauth.eveonline.models import EveCorporationInfo
from allianceauth.services.hooks import get_extension_logger

from corptools.models import Starbase, Structure

from .app_settings import (
    FUELALERT_POS_ENABLED,
    FUELALERT_STALE_HOURS,
    FUELALERT_THRESHOLDS_HOURS,
)
from .core import format_remaining
from .forms import RecipientForm
from .helpers import estimate_starbases, visible_corp_audits
from .models import Recipient
from .tasks import send_message

logger = get_extension_logger(__name__)


def _visible_corporations(user):
    """EveCorporationInfo queryset of all corps whose structures the user may see."""
    corp_ids = visible_corp_audits(user).values_list("corporation_id", flat=True)
    return EveCorporationInfo.objects.filter(pk__in=corp_ids)


def _level(hours_left) -> str:
    """Bootstrap color for the remaining fuel: red <= 24h or empty, orange <= 72h, else green."""
    if hours_left is None or hours_left <= 24:
        return "danger"
    if hours_left <= 72:
        return "warning"
    return "success"


def _structure_rows(user, now):
    """Dashboard rows for all structures visible to the user; no fuel first, then most urgent."""
    stale_before = now - dt.timedelta(hours=FUELALERT_STALE_HOURS)
    structures = (
        Structure.objects.filter(corporation__in=visible_corp_audits(user))
        .select_related("corporation__corporation", "system_name", "type_name")
        .prefetch_related("structureservice_set")
    )
    rows = []
    for structure in structures:
        fuel = structure.fuel_expires
        has_fuel = fuel is not None and fuel > now
        hours_left = (fuel - now).total_seconds() / 3600 if has_fuel else None
        updated = structure.corporation.get_update_time("structures")
        rows.append(
            {
                "structure": structure,
                "remaining": format_remaining(fuel, now) if has_fuel else None,
                "level": _level(hours_left),
                "stale": updated is None or updated < stale_before,
                "services": [
                    s for s in structure.structureservice_set.all() if s.state != "cleanup"
                ],
                "sort": (has_fuel, fuel if has_fuel else now),
            }
        )
    rows.sort(key=lambda row: row["sort"])
    return rows


def _starbase_rows(user, now):
    """Dashboard rows for all POS visible to the user, with the calculated fuel end time."""
    stale_before = now - dt.timedelta(hours=FUELALERT_STALE_HOURS)
    starbases = Starbase.objects.filter(
        corporation__in=visible_corp_audits(user)
    ).select_related("corporation__corporation__alliance", "system", "moon", "type_name")
    rows = []
    for starbase, pos in estimate_starbases(starbases):
        fuel = pos.fuel_expires
        has_fuel = fuel is not None and fuel > now and starbase.state != "offline"
        hours_left = (fuel - now).total_seconds() / 3600 if has_fuel else None
        updated = starbase.corporation.get_update_time("starbases")
        name = (
            starbase.name
            or (starbase.moon.name if starbase.moon else "")
            or (starbase.system.name if starbase.system else "")
            or str(starbase.starbase_id)
        )
        rows.append(
            {
                "starbase": starbase,
                "pos": pos,
                "name": name,
                "remaining": format_remaining(fuel, now) if has_fuel else None,
                "level": _level(hours_left),
                "stale": updated is None or updated < stale_before,
                "sort": (has_fuel, fuel if has_fuel else now),
            }
        )
    rows.sort(key=lambda row: row["sort"])
    return rows


@login_required
@permission_required("fuelalert.basic_access")
def index(request):
    """Dashboard: fuel status of visible structures and the user's alert settings."""
    recipient = Recipient.objects.filter(user=request.user).first()
    form = RecipientForm(
        instance=recipient, corporations_qs=_visible_corporations(request.user)
    )
    now = timezone.now()
    context = {
        "rows": _structure_rows(request.user, now),
        "pos_rows": _starbase_rows(request.user, now) if FUELALERT_POS_ENABLED else [],
        "pos_enabled": FUELALERT_POS_ENABLED,
        "form": form,
        "recipient": recipient,
        "thresholds": sorted(set(FUELALERT_THRESHOLDS_HOURS), reverse=True),
    }
    return render(request, "fuelalert/index.html", context)


@login_required
@permission_required("fuelalert.basic_access")
@require_POST
def save_recipient(request):
    """Create or update the alert settings of the current user."""
    recipient = Recipient.objects.filter(user=request.user).first()
    form = RecipientForm(
        request.POST,
        instance=recipient,
        corporations_qs=_visible_corporations(request.user),
    )
    if form.is_valid():
        obj = form.save(commit=False)
        obj.user = request.user
        obj.save()
        form.save_m2m()
        messages.success(request, _("Alert settings saved."))
    else:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f"{form.fields[field].label}: {error}" if field in form.fields else error)
    return redirect("fuelalert:index")


@login_required
@permission_required("fuelalert.basic_access")
@require_POST
def send_test(request):
    """Queue a test message over the current user's channel."""
    recipient = Recipient.objects.filter(user=request.user, enabled=True).first()
    if not recipient:
        messages.warning(request, _("Save and enable your alert settings first."))
        return redirect("fuelalert:index")
    send_message.delay(
        recipient.pk, "⛽ *Fuel Alert* - test message. Your alerts are working."
    )
    messages.info(request, _("Test message queued. It should arrive within a minute."))
    return redirect("fuelalert:index")


@login_required
@permission_required("fuelalert.basic_access")
@require_POST
def delete_recipient(request):
    """Delete the alert settings (contact data and key) of the current user."""
    Recipient.objects.filter(user=request.user).delete()
    messages.success(request, _("Your alert settings were deleted."))
    return redirect("fuelalert:index")
