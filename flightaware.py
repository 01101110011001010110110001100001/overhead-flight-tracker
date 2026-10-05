# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# FlightAware AeroAPI client: fills in departure airport, destination airport,
# and aircraft type for a flight OpenSky has detected nearby.
#
# Uses GET /flights/{ident}?max_pages=1 (ident = the OpenSky callsign). That can
# return several flights with the same flight number (past, current, scheduled),
# so we pick the one that is CURRENTLY AIRBORNE: it has an actual departure time
# (actual_off) but no actual arrival time (actual_on).
#
# Cost control:
#   * Results are cached per aircraft (by icao24). Position updates and screen
#     changes reuse the cache and never trigger another FlightAware request.
#   * Each successful (HTTP 200) query is recorded in the budget tracker.
#   * We don't query at all once the budget is exhausted; OpenSky tracking
#     continues regardless.
#   * A 401 disables FlightAware for the session (bad key); a 429 starts a
#     cooldown. "Not found" results are cached so we don't keep retrying.
#
# This module has no board dependencies (only `time`); its parsing is unit-tested.

import time

AEROAPI_URL = "https://aeroapi.flightaware.com/aeroapi/flights/{}?max_pages=1"
REQUEST_TIMEOUT = 10
RATE_LIMIT_COOLDOWN = 65  # seconds to wait after a 429 (Personal = 10 q/min)


def _airport_code(airport):
    if not airport:
        return None
    return (airport.get("code_iata")
            or airport.get("code_icao")
            or airport.get("code"))


def match_airborne_flight(flights):
    """From AeroAPI's flight list, return the currently-airborne flight, or None.

    Airborne = departed (actual_off set) but not yet arrived (actual_on null).
    If several match, the most recently departed wins. Falls back to any flight
    reporting progress strictly between 0 and 100 percent.
    """
    airborne = [f for f in (flights or [])
                if f.get("actual_off") and not f.get("actual_on")]
    if airborne:
        airborne.sort(key=lambda f: f.get("actual_off") or "", reverse=True)
        return airborne[0]
    for flight in flights or []:
        progress = flight.get("progress_percent")
        if progress is not None and 0 < progress < 100:
            return flight
    return None


def extract_route(flight):
    """Pull origin/destination codes and aircraft type from a flight, or None."""
    if not flight:
        return None
    return {
        "origin": _airport_code(flight.get("origin")),
        "dest": _airport_code(flight.get("destination")),
        "type": flight.get("aircraft_type"),
    }


class FlightAwareClient:
    def __init__(self, requests_session, api_key, budget):
        self._requests = requests_session
        self._key = api_key
        self._budget = budget
        self._cache = {}          # icao24 -> route dict or None (not found)
        self._disabled = False    # True after a 401 (bad key)
        self._cooldown_until = 0.0
        self._last_query_ok = False

    def lookup(self, icao24, callsign):
        """Return {origin, dest, type} for this aircraft, or None.

        Cached per aircraft; a given icao24 is queried at most once. Returns None
        (without caching) when FlightAware is disabled, cooling down, out of
        budget, or the callsign is missing -- so OpenSky-only display is used and
        the flight can still be enriched later if conditions change.
        """
        if icao24 in self._cache:
            return self._cache[icao24]
        if self._disabled or not callsign:
            return None
        if time.monotonic() < self._cooldown_until:
            return None
        if not self._budget.can_query():
            return None  # budget exhausted -> keep tracking via OpenSky only

        self._last_query_ok = False
        result = self._query(callsign)
        if self._last_query_ok:
            # Cache found-or-not-found so we never re-query this aircraft.
            self._cache[icao24] = result
        return result

    def _query(self, callsign):
        url = AEROAPI_URL.format(callsign)
        headers = {"x-apikey": self._key, "Accept": "application/json; charset=UTF-8"}
        response = None
        try:
            response = self._requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
            status = response.status_code
            if status == 200:
                self._budget.record_query()   # billable
                self._last_query_ok = True
                flights = response.json().get("flights")
                return extract_route(match_airborne_flight(flights))
            if status == 401:
                print("FlightAware: 401 unauthorized (check API key); disabling.")
                self._disabled = True
                return None
            if status == 429:
                print("FlightAware: 429 rate limited; cooling down.")
                self._cooldown_until = time.monotonic() + RATE_LIMIT_COOLDOWN
                return None
            print("FlightAware: HTTP", status)
            return None
        except Exception as error:  # noqa: BLE001 -- best effort, never raise
            print("FlightAware: request failed:", error)
            return None
        finally:
            if response is not None:
                response.close()
