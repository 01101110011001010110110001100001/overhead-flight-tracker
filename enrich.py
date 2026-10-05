# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Aircraft enrichment for the ONE closest plane. OpenSky's live feed has no
# route, airline name, or aircraft type, so we look those up on adsbdb.
#
#   * ROUTE + AIRLINE -> adsbdb /callsign  (airline + origin/destination + coords)
#   * AIRCRAFT TYPE   -> adsbdb /aircraft by Mode-S hex
#
# Why adsbdb and not the data the OpenSky map uses (adsb.lol VRS standing data)?
# That host serves a Google Trust Services certificate, and CircuitPython's
# trimmed on-board CA bundle doesn't include that root -- so the board CANNOT
# verify it (and CircuitPython has no way to safely disable verification or add
# a second root). adsbdb uses a Let's Encrypt cert, which the board trusts.
#
# adsbdb routes are keyed by flight number and can be stale, so the displayed
# route is cross-checked by flight_filter.route_is_plausible() (the plane must
# actually be on the corridor); when it fails, the UI shows altitude instead.
# Net effect: we never show a wrong route, at the cost of showing fewer routes
# than the website.
#
# Everything is cached and best-effort: any failure returns empty fields rather
# than raising, so enrichment can never crash the main loop or hide a flight.
#
# Attribution: route data by David Taylor (Edinburgh) & Jim Mason (Glasgow);
# aircraft data from PlaneBase. Served via adsbdb (https://www.adsbdb.com/).

import gc

ADSBDB_CALLSIGN = "https://api.adsbdb.com/v0/callsign/{}"
ADSBDB_AIRCRAFT = "https://api.adsbdb.com/v0/aircraft/{}"
REQUEST_TIMEOUT = 8
CACHE_LIMIT = 64

EMPTY = {"airline": None, "origin": None, "dest": None,
         "o_lat": None, "o_lon": None, "d_lat": None, "d_lon": None,
         "type": None, "registration": None, "owner": None}


class AircraftEnricher:
    def __init__(self, requests_session):
        self._requests = requests_session
        self._route_cache = {}
        self._aircraft_cache = {}

    def _get_json(self, url):
        """GET a URL and return parsed JSON dict, or None on any problem."""
        # Free/defragment the heap before the TLS handshake; a low heap makes
        # HTTPS fail on the ESP32-S3, especially on back-to-back requests.
        gc.collect()
        response = None
        try:
            response = self._requests.get(
                url, headers={"Accept": "application/json"}, timeout=REQUEST_TIMEOUT)
            if response.status_code != 200:
                return None
            data = response.json()
        except Exception as error:  # noqa: BLE001 -- best effort, never raise
            print("enrich: lookup failed:", error)
            return None
        finally:
            if response is not None:
                response.close()
        return data if isinstance(data, dict) else None

    def _cache_put(self, cache, key, value):
        if len(cache) >= CACHE_LIMIT:
            cache.clear()
        cache[key] = value

    def _route(self, callsign):
        if callsign in self._route_cache:
            return self._route_cache[callsign]
        result = {"airline": None, "origin": None, "dest": None,
                  "o_lat": None, "o_lon": None, "d_lat": None, "d_lon": None}
        data = self._get_json(ADSBDB_CALLSIGN.format(callsign))
        try:
            route = data["response"]["flightroute"]
            result["airline"] = route.get("airline", {}).get("name")
            origin = route.get("origin", {})
            dest = route.get("destination", {})
            result["origin"] = origin.get("iata_code") or origin.get("icao_code")
            result["dest"] = dest.get("iata_code") or dest.get("icao_code")
            result["o_lat"] = origin.get("latitude")
            result["o_lon"] = origin.get("longitude")
            result["d_lat"] = dest.get("latitude")
            result["d_lon"] = dest.get("longitude")
        except (TypeError, KeyError, AttributeError):
            pass
        self._cache_put(self._route_cache, callsign, result)
        return result

    def _aircraft(self, icao24):
        if icao24 in self._aircraft_cache:
            return self._aircraft_cache[icao24]
        result = {"type": None, "registration": None, "owner": None}
        data = self._get_json(ADSBDB_AIRCRAFT.format(icao24))
        try:
            ac = data["response"]["aircraft"]
            result["type"] = ac.get("icao_type") or ac.get("type")
            result["registration"] = ac.get("registration")
            result["owner"] = ac.get("registered_owner")
        except (TypeError, KeyError, AttributeError):
            pass
        self._cache_put(self._aircraft_cache, icao24, result)
        return result

    def enrich(self, callsign, icao24, plane_lat=None, plane_lon=None):
        """Return {airline, origin, dest, o/d coords, type, registration, owner}.

        plane_lat/plane_lon are accepted for API compatibility (route-leg
        selection isn't possible with adsbdb's single-route data). Any field may
        be None; all lookups are cached and best-effort.
        """
        merged = dict(EMPTY)
        if callsign:
            merged.update(self._route(callsign))
        if icao24:
            merged.update(self._aircraft(icao24))
        return merged
