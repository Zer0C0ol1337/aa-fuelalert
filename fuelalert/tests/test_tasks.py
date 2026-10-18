"""Integration tests for the fuel check task and the dashboard (database, no network)."""

import datetime as dt
from unittest.mock import patch

from django.contrib.auth.models import Permission, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter, EveCorporationInfo

from corptools.models import CorporationAudit, Structure

from fuelalert.models import AlertLog, Recipient
from fuelalert.tasks import check_fuel_levels


def make_structure(audit, structure_id, hours_left, name="Test Astrahus", state="shield_vulnerable"):
    """Create a corptools structure with the given fuel left (None = no fuel)."""
    fuel = None if hours_left is None else timezone.now() + dt.timedelta(hours=hours_left)
    return Structure.objects.create(
        corporation=audit,
        structure_id=structure_id,
        name=name,
        fuel_expires=fuel,
        profile_id=1,
        reinforce_hour=18,
        state=state,
        system_id=30000142,
        type_id=35832,
    )


def give_main(user, character_id, corp):
    """Give a user a main character (Auth only opens app pages for users with a main)."""
    character = EveCharacter.objects.create(
        character_id=character_id,
        character_name=f"Char {character_id}",
        corporation_id=corp.corporation_id,
        corporation_name=corp.corporation_name,
        corporation_ticker=corp.corporation_ticker,
    )
    CharacterOwnership.objects.create(user=user, character=character, owner_hash=f"h{character_id}")
    user.profile.main_character = character
    user.profile.save()


class TestCheckFuelLevels(TestCase):
    """Alerts are logged once and sent only to entitled recipients."""

    @classmethod
    def setUpTestData(cls):
        """One corp with audit, a superuser recipient and a recipient without access."""
        cls.corp = EveCorporationInfo.objects.create(
            corporation_id=98000001,
            corporation_name="Ether Element",
            corporation_ticker="3THEL",
            member_count=10,
        )
        cls.audit = CorporationAudit.objects.create(corporation=cls.corp)
        cls.admin = User.objects.create_superuser("admin", "a@example.com", "x")
        cls.admin_recipient = Recipient.objects.create(
            user=cls.admin, phone="+491701234567", api_key="123456"
        )
        cls.admin_recipient.corporations.add(cls.corp)
        cls.member = User.objects.create_user("member")
        member_recipient = Recipient.objects.create(
            user=cls.member, phone="+491709999999", api_key="999"
        )
        member_recipient.corporations.add(cls.corp)

    @patch("fuelalert.tasks.send_message.apply_async")
    def test_low_fuel_alert_once(self, mock_send):
        """A structure at 20h fuel sends one message, the second run sends nothing."""
        make_structure(self.audit, 1001, 20)
        make_structure(self.audit, 1002, 500, name="Full Raitaru")
        check_fuel_levels()
        self.assertEqual(mock_send.call_count, 1)
        recipient_pk, text = mock_send.call_args.kwargs["args"]
        self.assertEqual(recipient_pk, self.admin_recipient.pk)
        self.assertIn("[3THEL] Test Astrahus", text)
        self.assertNotIn("Full Raitaru", text)
        self.assertEqual(
            set(AlertLog.objects.values_list("key", flat=True)), {"t168", "t72", "t24"}
        )
        check_fuel_levels()
        self.assertEqual(mock_send.call_count, 1)

    @patch("fuelalert.tasks.send_message.apply_async")
    def test_offline_and_cleanup(self, mock_send):
        """No fuel sends an offline alert; deleted structures lose their log entries."""
        structure = make_structure(self.audit, 2001, None)
        check_fuel_levels()
        self.assertIn("OUT OF FUEL", mock_send.call_args.kwargs["args"][1])
        structure.delete()
        check_fuel_levels()
        self.assertFalse(AlertLog.objects.exists())

    @patch("fuelalert.tasks.send_message.apply_async")
    def test_unanchoring_ignored(self, mock_send):
        """Structures in ignored states never alert."""
        make_structure(self.audit, 3001, None, state="unanchored")
        check_fuel_levels()
        mock_send.assert_not_called()

    @patch("fuelalert.tasks.send_message.apply_async")
    def test_member_with_access_but_no_corp_permission(self, mock_send):
        """basic_access alone does not reveal corp structures."""
        self.member.user_permissions.add(Permission.objects.get(codename="basic_access"))
        make_structure(self.audit, 4001, 5)
        check_fuel_levels()
        recipients = [call.kwargs["args"][0] for call in mock_send.call_args_list]
        self.assertEqual(recipients, [self.admin_recipient.pk])


class TestViews(TestCase):
    """Dashboard and settings views."""

    @classmethod
    def setUpTestData(cls):
        """Superuser plus a corp with one structure."""
        cls.corp = EveCorporationInfo.objects.create(
            corporation_id=98000002,
            corporation_name="Test Corp",
            corporation_ticker="TEST",
            member_count=1,
        )
        cls.audit = CorporationAudit.objects.create(corporation=cls.corp)
        make_structure(cls.audit, 5001, 30)
        make_structure(cls.audit, 5002, None, name="Empty Athanor")
        cls.admin = User.objects.create_superuser("admin2", "b@example.com", "x")
        give_main(cls.admin, 90000001, cls.corp)
        cls.nobody = User.objects.create_user("nobody")
        give_main(cls.nobody, 90000002, cls.corp)

    def test_index_renders(self):
        """Dashboard lists the structures, empty one first."""
        self.client.force_login(self.admin)
        response = self.client.get(reverse("fuelalert:index"))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("Test Astrahus", content)
        self.assertLess(content.index("Empty Athanor"), content.index("Test Astrahus"))

    def test_index_requires_permission(self):
        """Users without basic_access are redirected."""
        self.client.force_login(self.nobody)
        response = self.client.get(reverse("fuelalert:index"))
        self.assertEqual(response.status_code, 302)

    def test_save_and_delete_settings(self):
        """Saving creates the recipient with chosen corps, delete removes it."""
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("fuelalert:save_recipient"),
            {"channel": "whatsapp", "phone": "+491701234567", "api_key": "abc", "enabled": "on", "corporations": [self.corp.pk]},
        )
        self.assertEqual(response.status_code, 302)
        recipient = Recipient.objects.get(user=self.admin)
        self.assertEqual(list(recipient.corporations.all()), [self.corp])
        self.client.post(reverse("fuelalert:delete_recipient"))
        self.assertFalse(Recipient.objects.filter(user=self.admin).exists())

    def test_save_telegram(self):
        """Telegram settings save without phone/key; the username gets an @."""
        self.client.force_login(self.admin)
        self.client.post(
            reverse("fuelalert:save_recipient"),
            {"channel": "telegram", "telegram_user": "dave_eve", "enabled": "on"},
        )
        recipient = Recipient.objects.get(user=self.admin)
        self.assertEqual(recipient.channel, "telegram")
        self.assertEqual(recipient.telegram_user, "@dave_eve")

    def test_invalid_phone_rejected(self):
        """Phone numbers without + are not saved."""
        self.client.force_login(self.admin)
        self.client.post(
            reverse("fuelalert:save_recipient"),
            {"channel": "whatsapp", "phone": "01701234567", "api_key": "abc", "enabled": "on"},
        )
        self.assertFalse(Recipient.objects.filter(user=self.admin).exists())

    def test_get_on_post_routes_refused(self):
        """Changing routes only accept POST."""
        self.client.force_login(self.admin)
        response = self.client.get(reverse("fuelalert:delete_recipient"))
        self.assertEqual(response.status_code, 405)
