"""Tests for the CallMeBot senders and the send_message task (requests is mocked)."""

from unittest.mock import MagicMock, patch

import requests

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from fuelalert.messaging import (
    MessageError,
    MessageTemporaryError,
    send_telegram,
    send_whatsapp,
)
from fuelalert.models import Recipient
from fuelalert.tasks import send_message


def fake_response(status=200, text="Message queued"):
    """Minimal stand-in for a requests.Response."""
    response = MagicMock()
    response.status_code = status
    response.text = text
    return response


class TestSendWhatsApp(TestCase):
    """HTTP result handling for WhatsApp."""

    @patch("fuelalert.messaging.requests.get", return_value=fake_response())
    def test_success_sends_params(self, mock_get):
        """Phone, key and text go out as query parameters."""
        send_whatsapp("+491701234567", "key", "hello")
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params, {"phone": "+491701234567", "apikey": "key", "text": "hello"})

    @patch("fuelalert.messaging.requests.get", return_value=fake_response(200, "APIKey is invalid"))
    def test_wrong_key(self, _mock_get):
        """A rejected key raises a permanent error."""
        with self.assertRaises(MessageError):
            send_whatsapp("+491701234567", "bad", "hello")

    @patch("fuelalert.messaging.requests.get", return_value=fake_response(503))
    def test_server_error_is_temporary(self, _mock_get):
        """5xx is worth a retry."""
        with self.assertRaises(MessageTemporaryError):
            send_whatsapp("+491701234567", "key", "hello")

    @patch("fuelalert.messaging.requests.get", side_effect=requests.ConnectionError("down"))
    def test_network_error_is_temporary(self, _mock_get):
        """Connection problems are worth a retry."""
        with self.assertRaises(MessageTemporaryError):
            send_whatsapp("+491701234567", "key", "hello")


class TestSendTelegram(TestCase):
    """HTTP result handling for Telegram."""

    @patch("fuelalert.messaging.requests.get", return_value=fake_response(200, "Message to @dave_eve sent"))
    def test_success_plain_text(self, mock_get):
        """Username and text without *bold* markers go out as query parameters."""
        send_telegram("@dave_eve", "⛽ *Fuel Alert* - test")
        params = mock_get.call_args.kwargs["params"]
        self.assertEqual(params["user"], "@dave_eve")
        self.assertEqual(params["text"], "⛽ Fuel Alert - test")
        self.assertEqual(params["html"], "no")

    @patch("fuelalert.messaging.requests.get", return_value=fake_response(200, "Error: user not authorized"))
    def test_not_authorized(self, _mock_get):
        """An unauthorized user raises a permanent error."""
        with self.assertRaises(MessageError):
            send_telegram("@dave_eve", "hello")


class TestRecipientValidation(TestCase):
    """Contact data is required per channel."""

    def setUp(self):
        """A user to attach recipients to."""
        self.user = User.objects.create_user("v")

    def test_whatsapp_requires_phone_and_key(self):
        """WhatsApp without phone/key is invalid."""
        recipient = Recipient(user=self.user, channel="whatsapp")
        with self.assertRaises(ValidationError) as ctx:
            recipient.full_clean()
        self.assertIn("phone", ctx.exception.message_dict)
        self.assertIn("api_key", ctx.exception.message_dict)

    def test_telegram_requires_username(self):
        """Telegram without username is invalid."""
        recipient = Recipient(user=self.user, channel="telegram")
        with self.assertRaises(ValidationError) as ctx:
            recipient.full_clean()
        self.assertIn("telegram_user", ctx.exception.message_dict)

    def test_telegram_username_gets_at(self):
        """A username without @ is normalized."""
        recipient = Recipient(user=self.user, channel="telegram", telegram_user="dave_eve")
        recipient.full_clean()
        self.assertEqual(recipient.telegram_user, "@dave_eve")


class TestSendMessageTask(TestCase):
    """The task picks the channel, skips disabled recipients and swallows permanent errors."""

    @classmethod
    def setUpTestData(cls):
        """One WhatsApp and one Telegram recipient."""
        cls.wa = Recipient.objects.create(
            user=User.objects.create_user("wa"), phone="+491701234567", api_key="k"
        )
        cls.tg = Recipient.objects.create(
            user=User.objects.create_user("tg"), channel="telegram", telegram_user="@dave_eve"
        )

    @patch("fuelalert.messaging.send_telegram")
    @patch("fuelalert.messaging.send_whatsapp")
    def test_channel_routing(self, mock_wa, mock_tg):
        """Each recipient is sent over its own channel."""
        send_message(self.wa.pk, "hi")
        send_message(self.tg.pk, "hi")
        mock_wa.assert_called_once_with("+491701234567", "k", "hi")
        mock_tg.assert_called_once_with("@dave_eve", "hi")

    @patch("fuelalert.tasks.send_to_recipient")
    def test_disabled_skipped(self, mock_send):
        """Disabled recipient gets nothing."""
        Recipient.objects.filter(pk=self.wa.pk).update(enabled=False)
        send_message(self.wa.pk, "hi")
        mock_send.assert_not_called()

    @patch("fuelalert.tasks.send_to_recipient", side_effect=MessageError("API key rejected"))
    def test_permanent_error_no_crash(self, _mock_send):
        """A rejected message is logged, not raised."""
        send_message(self.wa.pk, "hi")
