"""Tests for the pure alert logic in fuelalert.core (no database needed)."""

import datetime as dt
from unittest import TestCase

from fuelalert.core import OFFLINE_KEY, evaluate_structure, format_remaining

NOW = dt.datetime(2026, 10, 18, 12, 0, tzinfo=dt.timezone.utc)
THRESHOLDS = [168, 72, 24, 6]


def run(hours_left, existing=(), **kwargs):
    """Evaluate a structure with the given fuel left in hours (None = no fuel)."""
    fuel = None if hours_left is None else NOW + dt.timedelta(hours=hours_left)
    return evaluate_structure(fuel, NOW, THRESHOLDS, set(existing), **kwargs)


class TestEvaluateStructure(TestCase):
    """Threshold, offline and re-arm behaviour."""

    def test_plenty_of_fuel_no_alert(self):
        """More fuel than the highest threshold sends nothing."""
        decision = run(500)
        self.assertIsNone(decision.alert_kind)
        self.assertEqual(decision.add_keys, [])

    def test_first_threshold(self):
        """Crossing 168h sends one threshold alert."""
        decision = run(160)
        self.assertEqual(decision.alert_kind, "threshold")
        self.assertEqual(decision.alert_hours, 168)
        self.assertEqual(decision.add_keys, ["t168"])

    def test_already_sent_is_quiet(self):
        """Same threshold again does nothing."""
        decision = run(150, existing={"t168"})
        self.assertIsNone(decision.alert_kind)

    def test_several_new_thresholds_one_message(self):
        """A structure first seen at 5h logs all thresholds but alerts once with the lowest."""
        decision = run(5)
        self.assertEqual(decision.alert_hours, 6)
        self.assertEqual(sorted(decision.add_keys), ["t168", "t24", "t6", "t72"])

    def test_next_threshold(self):
        """Moving from 72h to 24h sends the 24h alert."""
        decision = run(20, existing={"t168", "t72"})
        self.assertEqual(decision.alert_hours, 24)
        self.assertEqual(decision.add_keys, ["t24"])

    def test_offline(self):
        """No fuel sends one offline alert."""
        decision = run(None)
        self.assertEqual(decision.alert_kind, "offline")
        self.assertEqual(decision.add_keys, [OFFLINE_KEY])

    def test_expired_fuel_is_offline(self):
        """fuel_expires in the past counts as offline."""
        self.assertEqual(run(-1).alert_kind, "offline")

    def test_offline_only_once(self):
        """Offline alert is not repeated."""
        self.assertIsNone(run(None, existing={OFFLINE_KEY}).alert_kind)

    def test_offline_disabled(self):
        """FUELALERT_ALERT_OFFLINE=False suppresses offline alerts."""
        self.assertIsNone(run(None, alert_offline=False).alert_kind)

    def test_refuel_rearms(self):
        """After refueling to 200h all thresholds and the offline flag are cleared."""
        decision = run(200, existing={"t168", "t72", "t24", "t6", OFFLINE_KEY})
        self.assertIsNone(decision.alert_kind)
        self.assertEqual(
            sorted(decision.remove_keys), sorted(["t168", "t72", "t24", "t6", OFFLINE_KEY])
        )

    def test_rearm_margin(self):
        """Just above a threshold (inside the margin) keeps the log entry."""
        decision = run(25, existing={"t24"})
        self.assertNotIn("t24", decision.remove_keys)
        decision = run(27, existing={"t24"})
        self.assertIn("t24", decision.remove_keys)


class TestFormatRemaining(TestCase):
    """Remaining time formatting."""

    def test_days(self):
        """Days and hours."""
        self.assertEqual(format_remaining(NOW + dt.timedelta(hours=52), NOW), "2d 4h")

    def test_hours(self):
        """Hours and minutes."""
        self.assertEqual(format_remaining(NOW + dt.timedelta(minutes=125), NOW), "2h 5m")

    def test_minutes(self):
        """Minutes only."""
        self.assertEqual(format_remaining(NOW + dt.timedelta(minutes=45), NOW), "45m")

    def test_empty(self):
        """No fuel."""
        self.assertEqual(format_remaining(None, NOW), "0m")
