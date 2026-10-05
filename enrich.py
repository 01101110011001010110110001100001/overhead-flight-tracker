# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Aircraft enrichment via the free adsbdb API (no API key required).
# OpenSky's live feed has no route or aircraft type, so for the ONE closest
# plane we look up:
#   * route + airline  by callsign  -> https://api.adsbdb.com/v0/callsign/{cs}
#   * aircraft type    by Mode-S/hex -> https://api.adsbdb.com/v0/aircraft/{hex}
#
# Design notes:
#   * Results (including "not found") are cached so the same plane isn't
#     re-queried every refresh.
#   * Every lookup is best-effort: any failure (network, 404, bad JSON) returns
#     empty fields instead of raising, so enrichment can NEVER crash the main
#     loop or hide a flight.
#
# Attribution (required by adsbdb): flight-route data is the work of David Taylor
# (Edinburgh) and Jim Mason (Glasgow); aircraft data from PlaneBase. See README.

ROUTE_URL = "https://api.adsbdb.com/v0/callsign/{}"
AIRCRAFT_URL = "https://api.adsbdb.com/v0/aircraft/{}"
REQUEST_TIMEOUT = 8          # seconds; keep short so a slow API can't stall us
CACHE_LIMIT = 64             # bound memory: clear the cache past this many keys

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
        response = None
        try:
            response = self._requests.get(url, timeout=REQUEST_TIMEOUT)
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
        data = self._get_json(ROUTE_URL.format(callsign))
        try:
            route = data["response"]["flightroute"]
            result["airline"] = route.get("airline", {}).get("name")
            origin = route.get("origin", {})
            dest = route.get("destination", {})
            result["origin"] = origin.get("iata_code") or origin.get("icao_code")
            result["dest"] = dest.get("iata_code") or dest.get("icao_code")
            # Airport coords let us verify the plane is really on this route.
            result["o_lat"] = origin.get("latitude")
            result["o_lon"] = origin.get("longitude")
            result["d_lat"] = dest.get("latitude")
            result["d_lon"] = dest.get("longitude")
        except (TypeError, KeyError, AttributeError):
            pass  # leave as Nones -> caller falls back gracefully
        self._cache_put(self._route_cache, callsign, result)
        return result

    def _aircraft(self, icao24):
        if icao24 in self._aircraft_cache:
            return self._aircraft_cache[icao24]
        result = {"type": None, "registration": None, "owner": None}
        data = self._get_json(AIRCRAFT_URL.format(icao24))
        try:
            ac = data["response"]["aircraft"]
            result["type"] = ac.get("icao_type") or ac.get("type")
            result["registration"] = ac.get("registration")
            result["owner"] = ac.get("registered_owner")
        except (TypeError, KeyError, AttributeError):
            pass
        self._cache_put(self._aircraft_cache, icao24, result)
        return result

    def enrich(self, callsign, icao24):
        """Return {airline, origin, dest, type, registration, owner}.

        Any field may be None. Looks up route by callsign and aircraft by hex;
        both are cached and best-effort.
        """
        merged = dict(EMPTY)
        if callsign:
            merged.update(self._route(callsign))
        if icao24:
            merged.update(self._aircraft(icao24))
        return merged
