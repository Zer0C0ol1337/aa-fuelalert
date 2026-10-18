"""Sending alerts through the free CallMeBot APIs (WhatsApp and Telegram)."""

import requests

from allianceauth.services.hooks import get_extension_logger

from . import __version__
from .app_settings import (
    FUELALERT_CALLMEBOT_TELEGRAM_URL,
    FUELALERT_CALLMEBOT_URL,
    FUELALERT_HTTP_TIMEOUT,
)

logger = get_extension_logger(__name__)

USER_AGENT = f"aa-fuelalert/{__version__} (+https://github.com/Zer0C0ol1337/aa-fuelalert)"


class MessageError(Exception):
    """CallMeBot did not accept the message (wrong key, not authorized, ...)."""


class MessageTemporaryError(Exception):
    """Network problem or server error - worth retrying later."""


def _get(url: str, params: dict):
    """GET request to CallMeBot; maps network problems and 5xx/429 to MessageTemporaryError."""
    try:
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=FUELALERT_HTTP_TIMEOUT,
        )
    except requests.RequestException as ex:
        raise MessageTemporaryError(type(ex).__name__) from None
    if response.status_code >= 500 or response.status_code == 429:
        raise MessageTemporaryError(f"HTTP {response.status_code}")
    if response.status_code != 200:
        raise MessageError(f"HTTP {response.status_code}")
    return response


def send_whatsapp(phone: str, api_key: str, text: str) -> None:
    """Send one WhatsApp message to the user's own number."""
    response = _get(
        FUELALERT_CALLMEBOT_URL, {"phone": phone, "apikey": api_key, "text": text}
    )
    # CallMeBot answers HTTP 200 with a small HTML page, also for a wrong API key
    if "apikey is invalid" in response.text.lower():
        raise MessageError("API key rejected")


def send_telegram(username: str, text: str) -> None:
    """Send one Telegram message to a @username that has authorized @CallMeBot_txtbot."""
    # Telegram gets plain text: the WhatsApp *bold* markers are removed
    response = _get(
        FUELALERT_CALLMEBOT_TELEGRAM_URL,
        {"user": username, "text": text.replace("*", ""), "html": "no", "links": "no"},
    )
    body = response.text.lower()
    if "error" in body or "not authorized" in body or "unauthorized" in body:
        raise MessageError("Telegram user not authorized or unknown")


def send_to_recipient(recipient, text: str) -> None:
    """Send a message over the recipient's chosen channel."""
    if recipient.channel == recipient.Channel.TELEGRAM:
        send_telegram(recipient.telegram_user, text)
    else:
        send_whatsapp(recipient.phone, recipient.api_key, text)
