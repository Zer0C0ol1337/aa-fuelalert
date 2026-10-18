"""Settings for aa-fuelalert. All values can be overridden in local.py."""

from django.conf import settings

# Hours of fuel left at which an alert is sent (one message per threshold and refuel cycle)
FUELALERT_THRESHOLDS_HOURS = getattr(
    settings, "FUELALERT_THRESHOLDS_HOURS", [168, 72, 24, 6]
)

# Send an alert when a structure runs out of fuel / has no fuel at all (low power)
FUELALERT_ALERT_OFFLINE = getattr(settings, "FUELALERT_ALERT_OFFLINE", True)

# Structure states that never trigger alerts (structure is being anchored or unanchored)
FUELALERT_IGNORE_STATES = getattr(
    settings,
    "FUELALERT_IGNORE_STATES",
    ["anchoring", "anchor_vulnerable", "unanchored"],
)

# A threshold is re-armed only when fuel rises this many hours above it (avoids flapping)
FUELALERT_REARM_MARGIN_HOURS = getattr(settings, "FUELALERT_REARM_MARGIN_HOURS", 2)

# Seconds between two outgoing messages (CallMeBot is a free service, be gentle)
FUELALERT_SEND_DELAY_SECONDS = getattr(settings, "FUELALERT_SEND_DELAY_SECONDS", 5)

# Corptools structure data older than this is marked as stale on the dashboard
FUELALERT_STALE_HOURS = getattr(settings, "FUELALERT_STALE_HOURS", 24)

# CallMeBot WhatsApp endpoint
FUELALERT_CALLMEBOT_URL = getattr(
    settings, "FUELALERT_CALLMEBOT_URL", "https://api.callmebot.com/whatsapp.php"
)

# CallMeBot Telegram endpoint
FUELALERT_CALLMEBOT_TELEGRAM_URL = getattr(
    settings, "FUELALERT_CALLMEBOT_TELEGRAM_URL", "https://api.callmebot.com/text.php"
)

# HTTP timeout in seconds for CallMeBot requests
FUELALERT_HTTP_TIMEOUT = getattr(settings, "FUELALERT_HTTP_TIMEOUT", 30)

# Watch POS (control towers) too; their fuel end time is calculated from the fuel bay
FUELALERT_POS_ENABLED = getattr(settings, "FUELALERT_POS_ENABLED", True)

# Use 25 % less fuel for POS in systems where the owner's alliance has a sovereignty hub
FUELALERT_POS_SOV_DISCOUNT = getattr(settings, "FUELALERT_POS_SOV_DISCOUNT", True)

# POS states that never trigger alerts (reinforced towers burn strontium, not fuel)
FUELALERT_POS_IGNORE_STATES = getattr(
    settings, "FUELALERT_POS_IGNORE_STATES", ["unanchoring", "reinforced"]
)
