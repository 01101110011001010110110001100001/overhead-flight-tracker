# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Desktop tests for enrich.py's pure logic (leg selection) and its parsing/
# caching via a mock HTTP session. No network, no board.
#   python -m unittest discover -s tests

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import enrich


# Airports (iata, lat, lon)
DFW = {"iata": "DFW", "lat": 32.8968, "lon": -97.0380}
STL = {"iata": "STL", "lat": 38.7487, "lon": -90.3700}
PHX = {"iata": "PHX", "lat": 33.4342, "lon": -112.0116}
DEN = {"iata": "DEN", "lat": 39.8561, "lon": -104.6737}
CVG = {"iata": "CVG", "lat": 39.0489, "lon": -84.6678}


class PickLegTests(unittest.TestCase):
    def test_two_airports(self):
        leg = enrich._pick_leg([DFW, STL], 38.5, -90.3)
        self.assertEqual((leg[0]["iata"], leg[1]["iata"]), ("DFW", "STL"))

    def test_multi_leg_picks_current_leg_by_position(self):
        # PHX-DEN-CVG; a plane near Denver->Cincinnati should pick DEN-CVG.
        leg = enrich._pick_leg([PHX, DEN, CVG], 39.5, -95.0)
        self.assertEqual((leg[0]["iata"], leg[1]["iata"]), ("DEN", "CVG"))

    def test_multi_leg_first_leg(self):
        # A plane between Phoenix and Denver should pick PHX-DEN.
        leg = enrich._pick_leg([PHX, DEN, CVG], 36.5, -108.0)
        self.assertEqual((leg[0]["iata"], leg[1]["iata"]), ("PHX", "DEN"))

    def test_too_few_airports(self):
        self.assertIsNone(enrich._pick_leg([DFW], 38.5, -90.3))
        self.assertIsNone(enrich._pick_leg([], 38.5, -90.3))

    def test_no_position_falls_back_to_first_and_last(self):
        leg = enrich._pick_leg([PHX, DEN, CVG], None, None)
        self.assertEqual((leg[0]["iata"], leg[1]["iata"]), ("PHX", "CVG"))


# --- Mock HTTP plumbing to test parsing + merge without network -------------
class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
    def json(self):
        return self._payload
    def close(self):
        pass


class _MockSession:
    def __init__(self, responses):
        self._responses = responses  # dict: url-substring -> (status, payload)
    def get(self, url, headers=None, timeout=None):
        for key, (status, payload) in self._responses.items():
            if key in url:
                return _Resp(status, payload)
        return _Resp(404, {})


AAL_ROUTE = {"_airports": [
    {"iata": "DFW", "lat": 32.8968, "lon": -97.0380},
    {"iata": "STL", "lat": 38.7487, "lon": -90.3700},
]}
AAL_CALLSIGN = {"response": {"flightroute": {"airline": {"name": "American Airlines"}}}}
AAL_AIRCRAFT = {"response": {"aircraft": {
    "icao_type": "A319", "registration": "N766US", "registered_owner": "American Airlines"}}}


class EnrichMergeTests(unittest.TestCase):
    def test_full_merge_near_stl(self):
        session = _MockSession({
            "vrs-standing-data": (200, AAL_ROUTE),
            "adsbdb.com/v0/callsign": (200, AAL_CALLSIGN),
            "adsbdb.com/v0/aircraft": (200, AAL_AIRCRAFT),
        })
        e = enrich.AircraftEnricher(session)
        out = e.enrich("AAL2487", "a12345", 38.5, -90.3)
        self.assertEqual(out["airline"], "American Airlines")
        self.assertEqual(out["origin"], "DFW")
        self.assertEqual(out["dest"], "STL")
        self.assertEqual(out["type"], "A319")
        self.assertIsNotNone(out["d_lat"])

    def test_no_route_file_leaves_route_none(self):
        session = _MockSession({
            "adsbdb.com/v0/callsign": (200, AAL_CALLSIGN),
            "adsbdb.com/v0/aircraft": (200, AAL_AIRCRAFT),
            # no vrs-standing-data entry -> 404
        })
        e = enrich.AircraftEnricher(session)
        out = e.enrich("AAL2487", "a12345", 38.5, -90.3)
        self.assertEqual(out["airline"], "American Airlines")
        self.assertIsNone(out["origin"])
        self.assertEqual(out["type"], "A319")

    def test_all_failures_return_empty(self):
        class Boom:
            def get(self, url, headers=None, timeout=None):
                raise OSError("down")
        out = enrich.AircraftEnricher(Boom()).enrich("X", "y", 1.0, 2.0)
        self.assertTrue(all(v is None for v in out.values()))


if __name__ == "__main__":
    unittest.main()
