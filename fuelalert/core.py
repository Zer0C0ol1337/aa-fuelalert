"""Pure alert logic (no database, no network), so it can be tested on its own."""

import datetime as dt
from dataclasses import dataclass, field

OFFLINE_KEY = "offline"


def threshold_key(hours: int) -> str:
    """Key under which a sent threshold alert is stored, e.g. 24 -> 't24'."""
    return f"t{int(hours)}"


@dataclass
class Decision:
    """Result for one structure: which alert to send and which log keys to add or remove."""

    alert_kind: str | None = None  # "offline", "threshold" or None
    alert_hours: int | None = None  # the most urgent newly crossed threshold
    add_keys: list[str] = field(default_factory=list)
    remove_keys: list[str] = field(default_factory=list)


def evaluate_structure(
    fuel_expires: dt.datetime | None,
    now: dt.datetime,
    thresholds: list[int],
    existing_keys: set[str],
    alert_offline: bool = True,
    rearm_margin_hours: float = 2,
) -> Decision:
    """Decide what to do for one structure based on its fuel end time and already sent alerts."""
    decision = Decision()

    # Out of fuel (or never fueled): one offline alert until the structure is refueled
    if fuel_expires is None or fuel_expires <= now:
        if alert_offline and OFFLINE_KEY not in existing_keys:
            decision.alert_kind = "offline"
            decision.add_keys.append(OFFLINE_KEY)
        return decision

    if OFFLINE_KEY in existing_keys:
        decision.remove_keys.append(OFFLINE_KEY)

    remaining_hours = (fuel_expires - now).total_seconds() / 3600
    newly_crossed = []
    for hours in sorted(set(thresholds), reverse=True):
        key = threshold_key(hours)
        if remaining_hours <= hours:
            if key not in existing_keys:
                newly_crossed.append(hours)
                decision.add_keys.append(key)
        elif remaining_hours > hours + rearm_margin_hours and key in existing_keys:
            # Refueled well above this threshold -> it may fire again next cycle
            decision.remove_keys.append(key)

    if newly_crossed:
        # Only one message per structure and run, naming the most urgent threshold
        decision.alert_kind = "threshold"
        decision.alert_hours = min(newly_crossed)
    return decision


def format_remaining(fuel_expires: dt.datetime | None, now: dt.datetime) -> str:
    """Human readable remaining fuel time, e.g. '2d 4h' or '45m'."""
    if fuel_expires is None or fuel_expires <= now:
        return "0m"
    total_minutes = int((fuel_expires - now).total_seconds() // 60)
    days, rest = divmod(total_minutes, 1440)
    hours, minutes = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"
