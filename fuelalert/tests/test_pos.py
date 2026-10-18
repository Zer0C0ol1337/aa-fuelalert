"""Tests for the POS fuel calculation (pure logic) and POS alerts/dashboard (database)."""

import datetime as dt
from unittest import TestCase as PlainTestCase
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from allianceauth.eveonline.models import EveAllianceInfo, EveCorporationInfo

from corptools.models import CorporationAudit, Starbase, SovereigntyHub
from eve_sde.models import ItemType

from fuelalert.models import AlertLog, Recipient
from fuelalert.pos import estimate, parse_fuels, tower_profile
from fuelalert.tasks import check_fuel_levels

NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.timezone.utc)


class TestTowerProfile(PlainTestCase):
    """Size and faction tier from the type name."""

    def test_empire_large(self):
        """Empire large tower: 40/h."""
        profile = tower_profile("Caldari Control Tower")
        self.assertEqual((profile.size, profile.faction_factor, profile.base_rate), ("large", 1.0, 40))

    def test_sizes(self):
        """Medium and small suffixes."""
        self.assertEqual(tower_profile("Amarr Control Tower Medium").base_rate, 20)
        self.assertEqual(tower_profile("Gallente Control Tower Small").base_rate, 10)

    def test_faction_tiers(self):
        """Tier 2 prefixes win over the tier 1 name they contain."""
        self.assertEqual(tower_profile("Dark Blood Control Tower").faction_factor, 0.8)
        self.assertEqual(tower_profile("Blood Control Tower Small").faction_factor, 0.9)
        self.assertEqual(tower_profile("Dread Guristas Control Tower Medium").faction_factor, 0.8)
        self.assertEqual(tower_profile("Guristas Control Tower").faction_factor, 0.9)
        self.assertEqual(tower_profile("True Sansha Control Tower").faction_factor, 0.8)
        self.assertEqual(tower_profile("Sansha Control Tower").faction_factor, 0.9)

    def test_unknown_name_is_large_empire(self):
        """Missing type name falls back to the highest consumption (alerts rather too early)."""
        profile = tower_profile(None)
        self.assertEqual((profile.base_rate, profile.faction_factor), (40, 1.0))


class TestParseFuels(PlainTestCase):
    """Corptools text formats."""

    def test_python_repr(self):
        """Corptools stores str(list of dicts)."""
        self.assertEqual(parse_fuels("[{'type_id': 4051, 'quantity': 100}]"), [{"type_id": 4051, "quantity": 100}])

    def test_json(self):
        """JSON works too."""
        self.assertEqual(parse_fuels('[{"type_id": 4051, "quantity": 5}]'), [{"type_id": 4051, "quantity": 5}])

    def test_garbage(self):
        """Empty or broken text gives an empty list."""
        self.assertEqual(parse_fuels(""), [])
        self.assertEqual(parse_fuels("not a list"), [])


class TestEstimate(PlainTestCase):
    """Fuel end time."""

    FUELS = "[{'type_id': 4051, 'quantity': 4000}, {'type_id': 16275, 'quantity': 8000}]"

    def test_large_empire(self):
        """4000 blocks at 40/h = 100h; strontium is ignored."""
        pos = estimate("Caldari Control Tower", self.FUELS, NOW, sov_discount=False)
        self.assertEqual(pos.fuel_blocks, 4000)
        self.assertEqual(pos.blocks_per_hour, 40)
        self.assertEqual(pos.fuel_expires, NOW + dt.timedelta(hours=100))

    def test_sov_and_faction(self):
        """Tier 2 large in sov: 40 * 0.8 * 0.75 = 24/h."""
        pos = estimate("Shadow Control Tower", self.FUELS, NOW, sov_discount=True)
        self.assertEqual(pos.blocks_per_hour, 24)
        self.assertTrue(pos.sov_discount)

    def test_no_blocks(self):
        """No fuel blocks means no end time."""
        pos = estimate("Caldari Control Tower", "[]", NOW, sov_discount=False)
        self.assertIsNone(pos.fuel_expires)


class TestPosAlerts(TestCase):
    """POS take part in the fuel check and show on the dashboard."""

    @classmethod
    def setUpTestData(cls):
        """Alliance corp with audit, a large Caldari tower type and a superuser recipient."""
        alliance = EveAllianceInfo.objects.create(
            alliance_id=99000001, alliance_name="IGC", alliance_ticker="IGC", executor_corp_id=98000010
        )
        cls.corp = EveCorporationInfo.objects.create(
            corporation_id=98000010,
            corporation_name="Ether Element",
            corporation_ticker="3THEL",
            member_count=10,
            alliance=alliance,
        )
        cls.audit = CorporationAudit.objects.create(corporation=cls.corp)
        cls.tower = ItemType.objects.create(id=16213, name="Caldari Control Tower")
        cls.admin = User.objects.create_superuser("posadmin", "p@example.com", "x")
        recipient = Recipient.objects.create(user=cls.admin, phone="+491701234567", api_key="k")
        recipient.corporations.add(cls.corp)

    def make_pos(self, starbase_id, blocks, state="online"):
        """Create a starbase whose fuel bay was read just now."""
        self.audit.update_timestamps["starbases"] = timezone.now().isoformat()
        self.audit.save()
        return Starbase.objects.create(
            corporation=self.audit,
            starbase_id=starbase_id,
            name="Moon Goo Tower",
            state=state,
            type_name=self.tower,
            fuels=str([{"type_id": 4051, "quantity": blocks}]),
        )

    @patch("fuelalert.tasks.send_message.apply_async")
    def test_low_pos_alerts(self, mock_send):
        """800 blocks at 40/h = 20h left: one alert marked as calculated."""
        self.make_pos(7001, 800)
        check_fuel_levels()
        text = mock_send.call_args.kwargs["args"][1]
        self.assertIn("POS [3THEL] Moon Goo Tower", text)
        self.assertIn("(calculated)", text)
        self.assertTrue(AlertLog.objects.filter(structure_id=7001, key="t24").exists())

    @patch("fuelalert.tasks.send_message.apply_async")
    def test_full_pos_quiet(self, mock_send):
        """28800 blocks = 30 days: nothing to send."""
        self.make_pos(7002, 28800)
        check_fuel_levels()
        mock_send.assert_not_called()

    @patch("fuelalert.tasks.send_message.apply_async")
    def test_offline_pos(self, mock_send):
        """An offline tower alerts as offline even with fuel in the bay."""
        self.make_pos(7003, 28800, state="offline")
        check_fuel_levels()
        self.assertIn("POS OFFLINE", mock_send.call_args.kwargs["args"][1])

    @patch("fuelalert.tasks.send_message.apply_async")
    def test_reinforced_ignored(self, mock_send):
        """Reinforced towers burn strontium and are skipped."""
        self.make_pos(7004, 10, state="reinforced")
        check_fuel_levels()
        mock_send.assert_not_called()

    def test_sov_discount_from_hub(self):
        """A sov hub of an alliance corp in the tower's system gives 25 % less fuel."""
        from fuelalert.helpers import estimate_starbases

        starbase = self.make_pos(7005, 3000)
        Starbase.objects.filter(pk=starbase.pk).update(system_id=None)
        starbase.refresh_from_db()
        starbase.system_id = 30000142  # in-memory only, no SolarSystem row needed
        SovereigntyHub.objects.create(corporation=self.audit, hub_id=1, solar_system_id=30000142)
        (_, pos), = estimate_starbases([starbase])
        self.assertTrue(pos.sov_discount)
        self.assertEqual(pos.blocks_per_hour, 30)

    def test_dashboard_lists_pos(self):
        """The dashboard shows the POS table with blocks per hour."""
        from fuelalert.tests.test_tasks import give_main

        give_main(self.admin, 90000010, self.corp)
        self.make_pos(7006, 4000)
        self.client.force_login(self.admin)
        content = self.client.get(reverse("fuelalert:index")).content.decode()
        self.assertIn("POS fuel (calculated)", content)
        self.assertIn("Moon Goo Tower", content)
        self.assertIn("4000", content)
