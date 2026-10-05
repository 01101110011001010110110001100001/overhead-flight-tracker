# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Desktop unit tests for flight_filter.py.
#
# These run on a normal computer (NOT the board). From the repo root:
#     python -m unittest discover -s tests
# or simply:
#     python tests/test_flight_filter.py
#
# They need nothing from CircuitPython and no API credentials.

import os
import sys
import unittest

# Make the repo root importable so we can `import flight_filter`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flight_filter as ff


def make_state(callsign="TEST123", lat=40.7128, lon=-74.0060,
               baro=3000.0, geo=3100.0, on_ground=False, time_position=1000,
               vertical_rate=0.0):
    """Build an OpenSky-style state vector with sensible defaults."""
    state = [None] * 17
    state[ff.CALLSIGN] = callsign
    state[ff.TIME_POSITION] = time_position
    state[ff.LONGITUDE] = lon
    state[ff.LATITUDE] = lat
    state[ff.BARO_ALTITUDE] = baro
    state[ff.ON_GROUND] = on_ground
    state[ff.GEO_ALTITUDE] = geo
    state[ff.VERTICAL_RATE] = vertical_rate
    return state


HOME_LAT = 40.7128
HOME_LON = -74.0060


class HaversineTests(unittest.TestCase):
    def test_zero_distance(self):
        self.assertAlmostEqual(
            ff.haversine_km(HOME_LAT, HOME_LON, HOME_LAT, HOME_LON), 0.0, places=6)

    def test_known_distance_nyc_to_la(self):
        # NYC -> LA is ~3,936 km; allow a generous tolerance.
        d = ff.haversine_km(40.7128, -74.0060, 34.0522, -118.2437)
        self.assertTrue(3900 < d < 3980, "got {}".format(d))


class SelectClosestTests(unittest.TestCase):
    def test_picks_nearest_of_several(self):
        near = make_state(callsign="NEAR", lat=40.72, lon=-74.00)
        far = make_state(callsign="FAR", lat=40.78, lon=-74.00)
        result = ff.select_closest([far, near], HOME_LAT, HOME_LON,
                                   radius_km=50, now=1000, max_age_s=60)
        self.assertIsNotNone(result["flight"])
        self.assertEqual(result["flight"]["state"][ff.CALLSIGN], "NEAR")

    def test_excludes_on_ground(self):
        grounded = make_state(on_ground=True)
        result = ff.select_closest([grounded], HOME_LAT, HOME_LON,
                                   radius_km=50, now=1000)
        self.assertIsNone(result["flight"])

    def test_excludes_missing_position(self):
        s = make_state()
        s[ff.LATITUDE] = None
        result = ff.select_closest([s], HOME_LAT, HOME_LON, radius_km=50, now=1000)
        self.assertIsNone(result["flight"])

    def test_excludes_outside_radius(self):
        # ~0.2 deg north is ~22 km away; radius of 5 km excludes it.
        s = make_state(lat=40.9128)
        result = ff.select_closest([s], HOME_LAT, HOME_LON, radius_km=5, now=1000)
        self.assertIsNone(result["flight"])

    def test_stale_only_flag(self):
        # Within radius but the position is 500 s old vs now=1000 -> stale.
        s = make_state(time_position=500)
        result = ff.select_closest([s], HOME_LAT, HOME_LON, radius_km=50,
                                   now=1000, max_age_s=60)
        self.assertIsNone(result["flight"])
        self.assertTrue(result["stale_only"])

    def test_not_stale_when_fresh(self):
        s = make_state(time_position=980)
        result = ff.select_closest([s], HOME_LAT, HOME_LON, radius_km=50,
                                   now=1000, max_age_s=60)
        self.assertIsNotNone(result["flight"])
        self.assertFalse(result["stale_only"])

    def test_empty_input(self):
        result = ff.select_closest([], HOME_LAT, HOME_LON, radius_km=50, now=1000)
        self.assertIsNone(result["flight"])
        self.assertFalse(result["stale_only"])


class FormatFlightTests(unittest.TestCase):
    def test_imperial_conversion(self):
        s = make_state(callsign="UAL123 ", baro=3048.0)  # 3048 m = 10000 ft
        flight = {"state": s, "distance_km": 8.04672}     # = 5.0 mi
        out = ff.format_flight(flight, units="imperial")
        self.assertEqual(out["callsign"], "UAL123")       # trimmed
        self.assertEqual(out["altitude"], "10000 ft")
        self.assertEqual(out["distance"], "5.0 mi")

    def test_metric_conversion(self):
        s = make_state(baro=3000.0)
        flight = {"state": s, "distance_km": 3.0}
        out = ff.format_flight(flight, units="metric")
        self.assertEqual(out["altitude"], "3000 m")
        self.assertEqual(out["distance"], "3.0 km")

    def test_missing_callsign(self):
        s = make_state(callsign=None)
        out = ff.format_flight({"state": s, "distance_km": 1.0})
        self.assertEqual(out["callsign"], "UNKNOWN")

    def test_blank_callsign(self):
        s = make_state(callsign="   ")
        out = ff.format_flight({"state": s, "distance_km": 1.0})
        self.assertEqual(out["callsign"], "UNKNOWN")

    def test_missing_baro_falls_back_to_geo(self):
        s = make_state(baro=None, geo=3048.0)
        out = ff.format_flight({"state": s, "distance_km": 1.0}, units="imperial")
        self.assertEqual(out["altitude"], "10000 ft")

    def test_missing_all_altitude(self):
        s = make_state(baro=None, geo=None)
        out = ff.format_flight({"state": s, "distance_km": 1.0})
        self.assertEqual(out["altitude"], "ALT --")


class ProximityColorTests(unittest.TestCase):
    def test_far_is_green(self):
        self.assertEqual(ff.proximity_color(10.0, 10.0), ff.PROX_FAR)

    def test_overhead_is_red(self):
        self.assertEqual(ff.proximity_color(0.0, 10.0), ff.PROX_NEAR)

    def test_halfway_is_amber(self):
        self.assertEqual(ff.proximity_color(5.0, 10.0), ff.PROX_MID)

    def test_monotonic_warming(self):
        # Red channel should not decrease as the plane gets closer.
        colors = [ff.proximity_color(d, 10.0) for d in (10, 7.5, 5, 2.5, 0)]
        reds = [(c >> 16) & 0xFF for c in colors]
        self.assertEqual(reds, sorted(reds))

    def test_zero_radius_safe(self):
        self.assertEqual(ff.proximity_color(1.0, 0.0), ff.PROX_NEAR)


class ClimbArrowTests(unittest.TestCase):
    def test_climbing(self):
        s = make_state(baro=3048.0, vertical_rate=5.0)
        out = ff.format_flight({"state": s, "distance_km": 1.0, "radius_km": 10.0})
        self.assertTrue(out["altitude"].endswith(" ^"))

    def test_descending(self):
        s = make_state(baro=3048.0, vertical_rate=-5.0)
        out = ff.format_flight({"state": s, "distance_km": 1.0, "radius_km": 10.0})
        self.assertTrue(out["altitude"].endswith(" v"))

    def test_level_has_no_arrow(self):
        s = make_state(baro=3048.0, vertical_rate=0.0)
        out = ff.format_flight({"state": s, "distance_km": 1.0, "radius_km": 10.0})
        self.assertEqual(out["altitude"], "10000 ft")

    def test_unknown_rate_has_no_arrow(self):
        s = make_state(baro=3048.0, vertical_rate=None)
        out = ff.format_flight({"state": s, "distance_km": 1.0, "radius_km": 10.0})
        self.assertEqual(out["altitude"], "10000 ft")

    def test_format_includes_color(self):
        s = make_state(baro=3048.0)
        out = ff.format_flight({"state": s, "distance_km": 10.0, "radius_km": 10.0})
        self.assertEqual(out["color"], ff.PROX_FAR)


class SelectColorIntegrationTests(unittest.TestCase):
    def test_selection_carries_radius_for_color(self):
        s = make_state(lat=40.7128, lon=-74.0060)  # distance ~0 -> red
        result = ff.select_closest([s], HOME_LAT, HOME_LON, radius_km=10,
                                   now=1000, max_age_s=60)
        out = ff.format_flight(result["flight"])
        self.assertEqual(out["color"], ff.PROX_NEAR)


class EnrichedFlightTests(unittest.TestCase):
    def _flight(self, callsign="EDV4648", dist_km=12.87, radius=40.0):
        # 12.87 km ~= 8 mi
        return {"state": make_state(callsign=callsign), "distance_km": dist_km,
                "radius_km": radius}

    def test_full_airline_route_type(self):
        enr = {"airline": "Endeavor Air", "origin": "LEX", "dest": "ATL",
               "type": "CRJ9", "registration": "N304PQ", "owner": None}
        out = ff.format_enriched_flight(self._flight(), enr, units="imperial")
        self.assertEqual(out["line1"], "Endeavor")      # first word (name > 10)
        self.assertEqual(out["line2"], "LEX>ATL")
        self.assertEqual(out["line3"], "CRJ9 8mi")

    def test_short_airline_kept_whole(self):
        enr = {"airline": "Delta", "origin": "STL", "dest": "JFK", "type": "A320"}
        out = ff.format_enriched_flight(self._flight(), enr)
        self.assertEqual(out["line1"], "Delta")

    def test_ga_fallback_owner_and_registration(self):
        enr = {"airline": None, "origin": None, "dest": None,
               "type": "C172", "registration": "N512WT", "owner": "Flying Club"}
        out = ff.format_enriched_flight(self._flight("N512WT", dist_km=3.2), enr)
        self.assertEqual(out["line1"], "Flying Clu")    # owner, truncated to 10
        self.assertEqual(out["line2"], "N512WT")        # registration as route
        self.assertEqual(out["line3"], "C172 2mi")

    def test_no_enrichment_at_all(self):
        out = ff.format_enriched_flight(self._flight("UAL9"), {}, units="imperial")
        self.assertEqual(out["line1"], "UAL9")          # callsign
        self.assertEqual(out["line2"], "--")
        self.assertEqual(out["line3"], "8mi")           # distance only

    def test_missing_type_shows_distance_only(self):
        enr = {"airline": "United", "origin": "ORD", "dest": "DEN", "type": None}
        out = ff.format_enriched_flight(self._flight(), enr)
        self.assertEqual(out["line3"], "8mi")

    def test_metric_distance(self):
        enr = {"airline": "KLM", "origin": "AMS", "dest": "LHR", "type": "B738"}
        out = ff.format_enriched_flight(self._flight(dist_km=10.0), enr, units="metric")
        self.assertEqual(out["line3"], "B738 10km")

    def test_lines_fit_panel(self):
        enr = {"airline": "Verylongairlinename Co", "origin": "ABCD",
               "dest": "WXYZ", "type": "SUPERLONGTYPE"}
        out = ff.format_enriched_flight(self._flight(), enr)
        for key in ("line1", "line2", "line3"):
            self.assertLessEqual(len(out[key]), ff.MAX_LINE,
                                 "{} too long: {!r}".format(key, out[key]))

    def test_color_by_proximity(self):
        enr = {"airline": "Delta", "origin": "A", "dest": "B", "type": "A320"}
        out = ff.format_enriched_flight(self._flight(dist_km=40.0, radius=40.0), enr)
        self.assertEqual(out["color"], ff.PROX_FAR)


class ScaleColorTests(unittest.TestCase):
    def test_full_is_unchanged(self):
        self.assertEqual(ff.scale_color(0x00CC33, 1.0), 0x00CC33)

    def test_zero_is_black(self):
        self.assertEqual(ff.scale_color(0xFFFFFF, 0.0), 0x000000)

    def test_half_dims_each_channel(self):
        self.assertEqual(ff.scale_color(0xFF8040, 0.5), 0x804020)

    def test_clamps_above_one(self):
        self.assertEqual(ff.scale_color(0x102030, 5.0), 0x102030)


class BboxTests(unittest.TestCase):
    def test_box_contains_home_and_is_small(self):
        box = ff.bbox_around(HOME_LAT, HOME_LON, radius_km=8)
        self.assertTrue(box["lamin"] < HOME_LAT < box["lamax"])
        self.assertTrue(box["lomin"] < HOME_LON < box["lomax"])
        # Area should be tiny (well under 25 sq deg -> 1 API credit).
        area = (box["lamax"] - box["lamin"]) * (box["lomax"] - box["lomin"])
        self.assertTrue(area < 25, "box area {} too big".format(area))


if __name__ == "__main__":
    unittest.main()
