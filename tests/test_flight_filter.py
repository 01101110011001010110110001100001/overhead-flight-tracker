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


class FlightColorTests(unittest.TestCase):
    def test_far_is_white(self):
        self.assertEqual(ff.flight_color(10.0, close_km=4.8), ff.COLOR_NORMAL)

    def test_super_close_is_red(self):
        self.assertEqual(ff.flight_color(2.0, close_km=4.8), ff.COLOR_CLOSE)

    def test_exactly_at_threshold_is_red(self):
        self.assertEqual(ff.flight_color(4.8, close_km=4.8), ff.COLOR_CLOSE)

    def test_just_beyond_threshold_is_white(self):
        self.assertEqual(ff.flight_color(4.81, close_km=4.8), ff.COLOR_NORMAL)


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
        out = ff.format_flight({"state": s, "distance_km": 10.0}, close_km=4.8)
        self.assertEqual(out["color"], ff.COLOR_NORMAL)


class SelectColorIntegrationTests(unittest.TestCase):
    def test_overhead_plane_is_red(self):
        s = make_state(lat=40.7128, lon=-74.0060)  # distance ~0 -> super close
        result = ff.select_closest([s], HOME_LAT, HOME_LON, radius_km=10,
                                   now=1000, max_age_s=60)
        out = ff.format_flight(result["flight"], close_km=4.8)
        self.assertEqual(out["color"], ff.COLOR_CLOSE)


class FormatFlightLinesTests(unittest.TestCase):
    def _flight(self, callsign="AAL2487", dist_km=12.87, baro=3048.0):
        # 12.87 km ~= 8 mi; baro 3048 m = 10000 ft
        return {"state": make_state(callsign=callsign, baro=baro),
                "distance_km": dist_km}

    def test_full_route_and_type(self):
        route = {"origin": "DFW", "dest": "STL", "type": "A319"}
        out = ff.format_flight_lines(self._flight(), route, units="imperial")
        self.assertEqual(out["line1"], "DFW>STL")
        self.assertEqual(out["line2"], "A319")
        self.assertEqual(out["line3"], "8.0 mi")

    def test_type_code_becomes_model_name(self):
        route = {"origin": "DFW", "dest": "STL", "type": "BCS1"}
        out = ff.format_flight_lines(self._flight(), route)
        self.assertEqual(out["line2"], "A220-100")   # not the raw "BCS1"

    def test_no_route_falls_back_to_callsign_and_altitude(self):
        out = ff.format_flight_lines(self._flight("UAL9"), None, units="imperial")
        self.assertEqual(out["line1"], "UAL9")        # callsign
        self.assertEqual(out["line2"], "10000 ft")    # altitude fallback
        self.assertEqual(out["line3"], "8.0 mi")

    def test_route_without_type_shows_altitude(self):
        route = {"origin": "DFW", "dest": "STL", "type": None}
        out = ff.format_flight_lines(self._flight(), route)
        self.assertEqual(out["line1"], "DFW>STL")
        self.assertEqual(out["line2"], "10000 ft")

    def test_partial_route_falls_back_to_callsign(self):
        route = {"origin": "DFW", "dest": None, "type": "A319"}
        out = ff.format_flight_lines(self._flight("AAL2487"), route)
        self.assertEqual(out["line1"], "AAL2487")     # need both ends for a route
        self.assertEqual(out["line2"], "A319")

    def test_missing_callsign_and_altitude(self):
        flight = {"state": make_state(callsign="", baro=None, geo=None),
                  "distance_km": 1.0}
        out = ff.format_flight_lines(flight, None)
        self.assertEqual(out["line1"], "UNKNOWN")
        self.assertEqual(out["line2"], "ALT --")

    def test_metric_distance(self):
        route = {"origin": "AMS", "dest": "LHR", "type": "B738"}
        out = ff.format_flight_lines(self._flight(dist_km=10.0), route, units="metric")
        self.assertEqual(out["line3"], "10.0 km")

    def test_lines_fit_panel(self):
        route = {"origin": "ABCDEF", "dest": "WXYZ12", "type": "SUPERLONGTYPE"}
        out = ff.format_flight_lines(self._flight(), route)
        for key in ("line1", "line2", "line3"):
            self.assertLessEqual(len(out[key]), ff.MAX_LINE,
                                 "{} too long: {!r}".format(key, out[key]))

    def test_far_plane_is_white(self):
        route = {"origin": "DFW", "dest": "STL", "type": "A319"}
        out = ff.format_flight_lines(self._flight(dist_km=40.0), route, close_km=4.8)
        self.assertEqual(out["color"], ff.COLOR_NORMAL)

    def test_super_close_plane_is_red(self):
        route = {"origin": "DFW", "dest": "STL", "type": "A319"}
        out = ff.format_flight_lines(self._flight(dist_km=2.0), route, close_km=4.8)
        self.assertEqual(out["color"], ff.COLOR_CLOSE)


class AircraftNameTests(unittest.TestCase):
    def test_known_codes(self):
        self.assertEqual(ff.aircraft_name("BCS1"), "A220-100")
        self.assertEqual(ff.aircraft_name("B738"), "737-800")
        self.assertEqual(ff.aircraft_name("A21N"), "A321neo")

    def test_case_insensitive(self):
        self.assertEqual(ff.aircraft_name("bcs1"), "A220-100")

    def test_unknown_falls_back_to_code(self):
        self.assertEqual(ff.aircraft_name("ZZZZ"), "ZZZZ")

    def test_none(self):
        self.assertIsNone(ff.aircraft_name(None))
        self.assertIsNone(ff.aircraft_name(""))

    def test_all_names_fit_panel(self):
        for code, name in ff.AIRCRAFT_NAMES.items():
            self.assertLessEqual(len(name), ff.MAX_LINE,
                                 "{} -> {!r} too long".format(code, name))


class GuessOperationTests(unittest.TestCase):
    def test_medical_callsigns(self):
        self.assertEqual(ff.guess_operation("MEDEVAC1"), "Medical")
        self.assertEqual(ff.guess_operation("LIFEGUARD"), "Medical")
        self.assertEqual(ff.guess_operation("ARCH3"), "Medical")  # STL air ambulance

    def test_other_missions(self):
        self.assertEqual(ff.guess_operation("POLICE1"), "Police")
        self.assertEqual(ff.guess_operation("CHOPPER4"), "News")
        self.assertEqual(ff.guess_operation("FIREBIRD"), "Fire")
        self.assertEqual(ff.guess_operation("RESCUE51"), "Rescue")
        self.assertEqual(ff.guess_operation("ARMY123"), "Military")

    def test_case_insensitive(self):
        self.assertEqual(ff.guess_operation("medevac1"), "Medical")

    def test_training_from_trainer_type(self):
        # No mission keyword in the callsign, but the type is a pure trainer.
        self.assertEqual(ff.guess_operation("N512DV", "DV20"), "Training")
        self.assertEqual(ff.guess_operation("N22R", "R22"), "Training")

    def test_callsign_beats_type(self):
        # A medical callsign wins even if it's flying a trainer-ish type.
        self.assertEqual(ff.guess_operation("MEDEVAC1", "DV20"), "Medical")

    def test_no_signal_returns_none(self):
        self.assertIsNone(ff.guess_operation("N123AB", "C172"))  # ordinary plane
        self.assertIsNone(ff.guess_operation("AAL2487", "A319"))  # airline, no route
        self.assertIsNone(ff.guess_operation("", None))

    def test_labels_fit_panel(self):
        for _, label in ff.OPERATION_KEYWORDS:
            self.assertLessEqual(len(label), ff.MAX_LINE,
                                 "{!r} too long".format(label))


class RoutelessMissionLineTests(unittest.TestCase):
    def _flight(self, callsign, dist_km=5.0, baro=300.0):
        return {"state": make_state(callsign=callsign, baro=baro),
                "distance_km": dist_km}

    def test_medical_heli_shows_mission(self):
        route = {"origin": None, "dest": None, "type": "EC35"}
        out = ff.format_flight_lines(self._flight("ARCH3"), route)
        self.assertEqual(out["line1"], "Medical")   # from the callsign
        self.assertEqual(out["line2"], "H135")       # friendly type still shows

    def test_trainer_shows_training(self):
        route = {"origin": None, "dest": None, "type": "DV20"}
        out = ff.format_flight_lines(self._flight("N512DV"), route)
        self.assertEqual(out["line1"], "Training")
        self.assertEqual(out["line2"], "DV20")

    def test_unknown_still_falls_back_to_callsign(self):
        route = {"origin": None, "dest": None, "type": "C172"}
        out = ff.format_flight_lines(self._flight("N123AB"), route)
        self.assertEqual(out["line1"], "N123AB")


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
