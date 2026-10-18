"""Shared helpers. Visibility follows corptools exactly, so access is managed in one place."""

from collections import defaultdict

from django.utils import timezone

from corptools.models import CorporationAudit, CorptoolsConfiguration, SovereigntyHub
from eve_sde.models import ItemType

from .app_settings import FUELALERT_POS_SOV_DISCOUNT
from .pos import FUEL_BLOCK_TYPE_IDS, PosEstimate, estimate


def visible_corp_audits(user):
    """CorporationAudit queryset whose structures the user may see (same rules as corptools)."""
    corps = CorporationAudit.objects.visible_to(user)
    if user.has_perm("corptools.holding_corp_structures"):
        corps = corps | CorptoolsConfiguration.get_solo().holding_corp_qs()
    return corps


def sov_systems_by_alliance() -> dict[int, set[int]]:
    """Systems with a sovereignty hub per alliance, from the Corptools hub data of audited corps."""
    result = defaultdict(set)
    rows = SovereigntyHub.objects.filter(
        corporation__corporation__alliance__isnull=False
    ).values_list("corporation__corporation__alliance__alliance_id", "solar_system_id")
    for alliance_id, system_id in rows:
        result[alliance_id].add(system_id)
    return result


def fuel_block_type_ids() -> set[int]:
    """Known fuel block IDs plus any SDE type named '... Fuel Block' (in case of new ones)."""
    ids = set(FUEL_BLOCK_TYPE_IDS)
    ids.update(
        ItemType.objects.filter(name__endswith="Fuel Block").values_list("id", flat=True)
    )
    return ids


def estimate_starbases(starbases) -> list[tuple]:
    """(starbase, PosEstimate) for each starbase; the fuel bay time is the last Corptools update."""
    sov = sov_systems_by_alliance() if FUELALERT_POS_SOV_DISCOUNT else {}
    block_ids = fuel_block_type_ids()
    now = timezone.now()
    result = []
    for starbase in starbases:
        corp = starbase.corporation.corporation
        alliance_id = corp.alliance.alliance_id if corp.alliance_id else None
        in_sov = bool(alliance_id) and starbase.system_id in sov.get(alliance_id, set())
        data_time = starbase.corporation.get_update_time("starbases") or now
        pos: PosEstimate = estimate(
            type_name=starbase.type_name.name if starbase.type_name else None,
            raw_fuels=starbase.fuels,
            data_time=data_time,
            sov_discount=in_sov,
            fuel_block_ids=block_ids,
        )
        result.append((starbase, pos))
    return result
