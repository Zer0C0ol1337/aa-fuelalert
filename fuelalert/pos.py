"""Fuel estimation for POS (control towers / starbases) from Corptools data.

ESI only reports the fuel bay contents of a POS, not when it runs dry, so the
end time is calculated here: fuel blocks / blocks used per hour.
Consumption (EVE University wiki, "POS Setup"): small 10, medium 20, large 40
blocks per hour; faction towers tier 1 use 10 % less, tier 2 20 % less; 25 %
less when the owner's alliance holds sovereignty in the system.
"""

import ast
import datetime as dt
import json
from dataclasses import dataclass

# Fuel block type IDs: Nitrogen (Caldari), Hydrogen (Minmatar), Helium (Amarr), Oxygen (Gallente)
FUEL_BLOCK_TYPE_IDS = {4051, 4246, 4247, 4312}

BASE_BLOCKS_PER_HOUR = {"small": 10, "medium": 20, "large": 40}

# Checked in this order, so "Dark Blood" wins over "Blood" etc.
FACTION_PREFIXES = (
    ("Dark Blood", 0.8),
    ("Domination", 0.8),
    ("Dread Guristas", 0.8),
    ("True Sansha", 0.8),
    ("Shadow", 0.8),
    ("Angel", 0.9),
    ("Blood", 0.9),
    ("Guristas", 0.9),
    ("Sansha", 0.9),
    ("Serpentis", 0.9),
)

SOV_FACTOR = 0.75


@dataclass
class TowerProfile:
    """Size and faction modifier of a control tower type."""

    size: str  # "small", "medium" or "large"
    faction_factor: float  # 1.0 for empire towers

    @property
    def base_rate(self) -> int:
        """Blocks per hour before faction and sov modifiers."""
        return BASE_BLOCKS_PER_HOUR[self.size]


@dataclass
class PosEstimate:
    """Calculated fuel status of one POS."""

    fuel_blocks: int
    blocks_per_hour: float
    sov_discount: bool
    fuel_expires: dt.datetime | None  # None = no fuel blocks at all


def tower_profile(type_name: str | None) -> TowerProfile:
    """Derive size and faction modifier from the tower type name, e.g. 'Angel Control Tower Medium'."""
    name = type_name or ""
    if name.endswith("Small"):
        size = "small"
    elif name.endswith("Medium"):
        size = "medium"
    else:
        size = "large"
    faction_factor = 1.0
    for prefix, factor in FACTION_PREFIXES:
        if name.startswith(prefix + " "):
            faction_factor = factor
            break
    return TowerProfile(size=size, faction_factor=faction_factor)


def parse_fuels(raw) -> list[dict]:
    """Corptools stores the fuel bay as text (Python repr or JSON of [{type_id, quantity}])."""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    for parser in (json.loads, ast.literal_eval):
        try:
            data = parser(raw)
        except (ValueError, SyntaxError, TypeError):
            continue
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    return []


def count_fuel_blocks(fuels: list[dict], fuel_block_ids: set[int]) -> int:
    """Sum of all fuel blocks in the fuel bay."""
    return sum(
        int(item.get("quantity") or 0)
        for item in fuels
        if int(item.get("type_id") or 0) in fuel_block_ids
    )


def estimate(
    type_name: str | None,
    raw_fuels,
    data_time: dt.datetime,
    sov_discount: bool,
    fuel_block_ids: set[int] = FUEL_BLOCK_TYPE_IDS,
) -> PosEstimate:
    """Estimate when a POS runs out of fuel, counted from the time the fuel bay was read."""
    profile = tower_profile(type_name)
    rate = profile.base_rate * profile.faction_factor
    if sov_discount:
        rate *= SOV_FACTOR
    blocks = count_fuel_blocks(parse_fuels(raw_fuels), fuel_block_ids)
    fuel_expires = data_time + dt.timedelta(hours=blocks / rate) if blocks > 0 else None
    return PosEstimate(
        fuel_blocks=blocks,
        blocks_per_hour=round(rate, 2),
        sov_discount=sov_discount,
        fuel_expires=fuel_expires,
    )
