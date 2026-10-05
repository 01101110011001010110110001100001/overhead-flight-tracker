# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Desktop tests for enrich.py parsing/caching/failure handling via a mock HTTP
# session. No network, no board.
#   python -m unittest discover -s tests

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import enrich


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
        self._responses = responses  # url-substring -> (status, payload)
        self.calls = 0
    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        for key, (status, payload) in self._responses.items():
            if key in url:
                return _Resp(status, payload)
        return _Resp(404, {})


AAL_CALLSIGN = {"response": {"flightroute": {
    "airline": {"name": "American Airlines"},
    "origin": {"iata_code": "DFW", "latitude": 32.8968, "longitude": -97.0380},
    "destination": {"iata_code": "STL", "latitude": 38.7487, "longitude": -90.3700},
}}}
AAL_AIRCRAFT = {"response": {"aircraft": {
    "icao_type": "A319", "registration": "N766US",
    "registered_owner": "American Airlines"}}}


class EnrichTests(unittest.TestCase):
    def test_full_merge(self):
        session = _MockSession({
            "adsbdb.com/v0/callsign": (200, AAL_CALLSIGN),
            "adsbdb.com/v0/aircraft": (200, AAL_AIRCRAFT),
        })
        e = enrich.AircraftEnricher(session)
        out = e.enrich("AAL2487", "a12345", 38.5, -90.3)
        self.assertEqual(out["airline"], "American Airlines")
        self.assertEqual(out["origin"], "DFW")
        self.assertEqual(out["dest"], "STL")
        self.assertEqual(out["d_lat"], 38.7487)
        self.assertEqual(out["type"], "A319")

    def test_caching_avoids_repeat_requests(self):
        session = _MockSession({
            "adsbdb.com/v0/callsign": (200, AAL_CALLSIGN),
            "adsbdb.com/v0/aircraft": (200, AAL_AIRCRAFT),
        })
        e = enrich.AircraftEnricher(session)
        e.enrich("AAL2487", "a12345")
        after_first = session.calls
        e.enrich("AAL2487", "a12345")  # same plane -> served from cache
        self.assertEqual(session.calls, after_first)

    def test_404_leaves_fields_none(self):
        session = _MockSession({})  # everything 404s
        out = enrich.AircraftEnricher(session).enrich("ZZZ999", "ffffff")
        self.assertTrue(all(v is None for v in out.values()))

    def test_exception_returns_empty(self):
        class Boom:
            def get(self, url, headers=None, timeout=None):
                raise OSError("network down")
        out = enrich.AircraftEnricher(Boom()).enrich("ANY", "hex")
        self.assertTrue(all(v is None for v in out.values()))


if __name__ == "__main__":
    unittest.main()
