# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Desktop tests for flightaware.py: airborne-flight matching, route extraction,
# and the client's caching / budget / error behavior (mock session + budget).
#   python -m unittest discover -s tests

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import flightaware as fa


# --- Pure parsing ----------------------------------------------------------
class MatchAirborneTests(unittest.TestCase):
    def test_picks_airborne_flight(self):
        flights = [
            {"ident": "AAL1", "actual_off": "08:00", "actual_on": "10:00"},  # landed
            {"ident": "AAL1", "actual_off": "12:00", "actual_on": None},     # airborne
            {"ident": "AAL1", "actual_off": None, "actual_on": None},        # scheduled
        ]
        self.assertEqual(fa.match_airborne_flight(flights)["actual_off"], "12:00")

    def test_most_recent_airborne_wins(self):
        flights = [
            {"actual_off": "2026-01-01T12:00Z", "actual_on": None},
            {"actual_off": "2026-01-01T15:00Z", "actual_on": None},
        ]
        self.assertEqual(
            fa.match_airborne_flight(flights)["actual_off"], "2026-01-01T15:00Z")

    def test_progress_fallback(self):
        flights = [{"actual_off": None, "actual_on": None, "progress_percent": 55}]
        self.assertIsNotNone(fa.match_airborne_flight(flights))

    def test_none_when_no_airborne(self):
        flights = [{"actual_off": "08:00", "actual_on": "10:00", "progress_percent": 100}]
        self.assertIsNone(fa.match_airborne_flight(flights))

    def test_empty(self):
        self.assertIsNone(fa.match_airborne_flight([]))
        self.assertIsNone(fa.match_airborne_flight(None))


class ExtractRouteTests(unittest.TestCase):
    def test_extract_iata_preferred(self):
        flight = {
            "origin": {"code_iata": "DFW", "code_icao": "KDFW"},
            "destination": {"code_iata": "STL", "code_icao": "KSTL"},
            "aircraft_type": "A319",
        }
        self.assertEqual(fa.extract_route(flight),
                         {"origin": "DFW", "dest": "STL", "type": "A319"})

    def test_extract_icao_when_no_iata(self):
        flight = {"origin": {"code_icao": "KDFW"}, "destination": {"code_icao": "KSTL"}}
        out = fa.extract_route(flight)
        self.assertEqual(out["origin"], "KDFW")
        self.assertEqual(out["dest"], "KSTL")
        self.assertIsNone(out["type"])

    def test_none_flight(self):
        self.assertIsNone(fa.extract_route(None))


# --- Client behavior (mock session + budget) -------------------------------
class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload or {}
    def json(self):
        return self._payload
    def close(self):
        pass


class _MockSession:
    def __init__(self, response):
        self.response = response
        self.calls = 0
        self.last_headers = None
    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        self.last_headers = headers
        return self.response


class _FakeBudget:
    def __init__(self, allow=True):
        self.allow = allow
        self.recorded = 0
    def can_query(self):
        return self.allow
    def record_query(self):
        self.recorded += 1


AIRBORNE = {"flights": [
    {"origin": {"code_iata": "DFW"}, "destination": {"code_iata": "STL"},
     "aircraft_type": "A319", "actual_off": "12:00", "actual_on": None},
]}


class ClientTests(unittest.TestCase):
    def test_success_and_caches_per_aircraft(self):
        session = _MockSession(_Resp(200, AIRBORNE))
        budget = _FakeBudget()
        client = fa.FlightAwareClient(session, "KEY", budget)
        out = client.lookup("abc123", "AAL2487")
        self.assertEqual(out, {"origin": "DFW", "dest": "STL", "type": "A319"})
        self.assertEqual(budget.recorded, 1)
        # key is sent in the x-apikey header
        self.assertEqual(session.last_headers.get("x-apikey"), "KEY")
        # second lookup of same aircraft -> cache, no new request
        client.lookup("abc123", "AAL2487")
        self.assertEqual(session.calls, 1)

    def test_not_found_is_cached(self):
        session = _MockSession(_Resp(200, {"flights": []}))
        client = fa.FlightAwareClient(session, "KEY", _FakeBudget())
        self.assertIsNone(client.lookup("abc", "ZZZ"))
        client.lookup("abc", "ZZZ")
        self.assertEqual(session.calls, 1)  # cached negative -> no re-query

    def test_budget_exhausted_skips_query(self):
        session = _MockSession(_Resp(200, AIRBORNE))
        client = fa.FlightAwareClient(session, "KEY", _FakeBudget(allow=False))
        self.assertIsNone(client.lookup("abc", "AAL1"))
        self.assertEqual(session.calls, 0)  # never queried

    def test_401_disables_client(self):
        session = _MockSession(_Resp(401))
        client = fa.FlightAwareClient(session, "BADKEY", _FakeBudget())
        self.assertIsNone(client.lookup("abc", "AAL1"))
        self.assertIsNone(client.lookup("def", "AAL2"))
        self.assertEqual(session.calls, 1)  # disabled after first 401

    def test_429_sets_cooldown(self):
        session = _MockSession(_Resp(429))
        client = fa.FlightAwareClient(session, "KEY", _FakeBudget())
        self.assertIsNone(client.lookup("abc", "AAL1"))
        self.assertIsNone(client.lookup("def", "AAL2"))  # in cooldown -> no query
        self.assertEqual(session.calls, 1)

    def test_missing_callsign(self):
        session = _MockSession(_Resp(200, AIRBORNE))
        client = fa.FlightAwareClient(session, "KEY", _FakeBudget())
        self.assertIsNone(client.lookup("abc", ""))
        self.assertEqual(session.calls, 0)

    def test_exception_is_swallowed(self):
        class Boom:
            def get(self, url, headers=None, timeout=None):
                raise OSError("down")
        client = fa.FlightAwareClient(Boom(), "KEY", _FakeBudget())
        self.assertIsNone(client.lookup("abc", "AAL1"))


if __name__ == "__main__":
    unittest.main()
