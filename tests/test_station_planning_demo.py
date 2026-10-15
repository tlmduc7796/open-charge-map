"""Boundary tests for fixture helpers; full dataset checks use the validator CLI."""

import unittest
from datetime import datetime

from scripts.prepare_station_planning_demo import distance_m, open_at


class DemoHelperTests(unittest.TestCase):
    def test_opening_hours_are_half_open(self):
        self.assertFalse(
            open_at("05:30 - 20:00", datetime.fromisoformat("2025-07-07T05:29:00+07:00"))
        )
        self.assertTrue(
            open_at("05:30 - 20:00", datetime.fromisoformat("2025-07-07T05:30:00+07:00"))
        )
        self.assertFalse(
            open_at("05:30 - 20:00", datetime.fromisoformat("2025-07-07T20:00:00+07:00"))
        )

    def test_overnight_hours(self):
        self.assertTrue(
            open_at("22:00 - 04:00", datetime.fromisoformat("2025-07-07T23:00:00+07:00"))
        )
        self.assertTrue(
            open_at("22:00 - 04:00", datetime.fromisoformat("2025-07-07T03:59:00+07:00"))
        )
        self.assertFalse(
            open_at("22:00 - 04:00", datetime.fromisoformat("2025-07-07T04:00:00+07:00"))
        )

    def test_unknown_hours_fail_instead_of_becoming_always_open(self):
        with self.assertRaises(ValueError):
            open_at("unknown", datetime.fromisoformat("2025-07-07T00:00:00+07:00"))

    def test_great_circle_units_and_coordinate_order(self):
        self.assertEqual(distance_m([106.7, 10.8], [106.7, 10.8]), 0)
        self.assertAlmostEqual(distance_m([0, 0], [0, 1]), 111195.08, places=1)
        self.assertAlmostEqual(distance_m([0, 60], [1, 60]), 55597.01, places=1)


if __name__ == "__main__":
    unittest.main()
