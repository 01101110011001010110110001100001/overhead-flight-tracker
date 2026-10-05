# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Desktop unit tests for clock.py (St. Louis / US Central time with DST).
# Run from the repo root:  python -m unittest discover -s tests
#
# Where available, results are cross-checked against Python's own IANA timezone
# database (zoneinfo). If zoneinfo is missing, those checks are skipped but the
# fixed-value checks still run.

import calendar
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import clock

try:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("America/Chicago")
except Exception:  # pragma: no cover
    _TZ = None


def utc_of(y, mo, d, h, mi):
    return calendar.timegm((y, mo, d, h, mi, 0, 0, 0, 0))


class CentralTimeTests(unittest.TestCase):
    def test_winter_is_cst(self):
        out = clock.format_central_clock(utc_of(2026, 1, 15, 18, 34))
        self.assertEqual(out["time"], "12:34 PM")
        self.assertEqual(out["abbr"], "CST")

    def test_summer_is_cdt(self):
        out = clock.format_central_clock(utc_of(2026, 7, 4, 18, 34))
        self.assertEqual(out["time"], "1:34 PM")
        self.assertEqual(out["abbr"], "CDT")

    def test_midnight_is_twelve_am(self):
        out = clock.format_central_clock(utc_of(2026, 7, 5, 5, 0))  # 00:00 CDT
        self.assertEqual(out["time"], "12:00 AM")

    def test_noon_is_twelve_pm(self):
        out = clock.format_central_clock(utc_of(2026, 12, 25, 18, 0))  # 12:00 CST
        self.assertEqual(out["time"], "12:00 PM")

    def test_dst_starts_second_sunday_march(self):
        # 2026: 2nd Sunday of March is the 8th.
        self.assertFalse(clock._is_us_dst(utc_of(2026, 3, 8, 7, 59)))  # 1:59 CST
        self.assertTrue(clock._is_us_dst(utc_of(2026, 3, 8, 8, 1)))    # 3:01 CDT

    def test_dst_ends_first_sunday_november(self):
        # 2026: 1st Sunday of November is the 1st.
        self.assertTrue(clock._is_us_dst(utc_of(2026, 11, 1, 6, 59)))   # 1:59 CDT
        self.assertFalse(clock._is_us_dst(utc_of(2026, 11, 1, 7, 1)))   # 1:01 CST

    def test_utc_from_components_epoch(self):
        self.assertEqual(clock.utc_from_components(1970, 1, 1, 0, 0, 0), 0)

    def test_utc_from_components_roundtrip(self):
        # Build a UTC timestamp from NTP-style components, then format it back.
        u = clock.utc_from_components(2026, 7, 4, 18, 34, 7)
        self.assertEqual(u, utc_of(2026, 7, 4, 18, 34) + 7)
        self.assertEqual(clock.format_central_clock(u)["time"], "1:34 PM")  # CDT

    def test_nth_sunday_helper(self):
        self.assertEqual(clock._nth_sunday(2026, 3, 2), 8)
        self.assertEqual(clock._nth_sunday(2026, 11, 1), 1)

    def test_date_format(self):
        # 2026-07-04 12:00 UTC -> morning Central, Saturday.
        out = clock.format_central_date(utc_of(2026, 7, 4, 12, 0))
        self.assertEqual(out, "SAT JUL 4")

    def test_date_rolls_back_across_utc_midnight(self):
        # 2026-07-04 02:00 UTC is still 2026-07-03 (21:00) in Central.
        out = clock.format_central_date(utc_of(2026, 7, 4, 2, 0))
        self.assertEqual(out, "FRI JUL 3")

    @unittest.skipIf(_TZ is None, "zoneinfo not available")
    def test_date_matches_zoneinfo(self):
        for day in range(0, 365, 11):
            u = utc_of(2026, 1, 1, 18, 0) + day * 86400
            ref = datetime.fromtimestamp(u, _TZ)
            expected = ref.strftime("%a %b %-d").upper()
            self.assertEqual(clock.format_central_date(u), expected,
                             "date mismatch at day {}".format(day))

    @unittest.skipIf(_TZ is None, "zoneinfo not available")
    def test_matches_zoneinfo_across_year(self):
        # Sample every ~5 days through 2026 and compare to the IANA database.
        for day in range(0, 365, 5):
            u = utc_of(2026, 1, 1, 12, 0) + day * 86400
            mine = clock.format_central_clock(u)
            ref = datetime.fromtimestamp(u, _TZ)
            self.assertEqual(mine["time"], ref.strftime("%-I:%M %p"),
                             "time mismatch at day {}".format(day))
            self.assertEqual(mine["abbr"], ref.strftime("%Z"),
                             "tz mismatch at day {}".format(day))


if __name__ == "__main__":
    unittest.main()
