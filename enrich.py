# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Aircraft enrichment for the ONE closest plane. OpenSky's live feed has no
# route, airline name, or aircraft type, so we look those up here.
#
# Sources (all free, no API key):
#   * ROUTE  -> adsb.lol "VRS standing data" static files. This is the SAME
#     dataset the OpenSky map (tar1090/readsb) uses, so routes match what you
#     see there. For multi-leg flights it lists every stop and we pick the
#     current leg using the plane's position.
#       https://vrs-standing-data.adsb.lol/routes/<CS[:2]>/<CALLSIGN>.json
#   * AIRLINE NAME -> adsbdb /callsign (its airline field is reliable; we ignore
#     its route, which is often stale).
#   * AIRCRAFT TYPE -> adsbdb /aircraft by Mode-S hex (tied to the physical
#     airframe, so it's reliable).
#
# Everything is cached and best-effort: any failure returns empty fields rather
# than raising, so enrichment can never crash the main loop or hide a flight.
#
# Attribution: routes via adsb.lol (VRS standing data); airline/aircraft via
# adsbdb (route data by David Taylor & Jim Mason; aircraft from PlaneBase).

from flight_filter import haversine_km

ADSBDB_CALLSIGN = "https://api.adsbdb.com/v0/callsign/{}"
ADSBDB_AIRCRAFT = "https://api.adsbdb.com/v0/aircraft/{}"
VRS_ROUTE = "https://vrs-standing-data.adsb.lol/routes/{}/{}.json"
REQUEST_TIMEOUT = 8
CACHE_LIMIT = 64

EMPTY = {"airline": None, "origin": None, "dest": None,
         "o_lat": None, "o_lon": None, "d_lat": None, "d_lon": None,
         "type": None, "registration": None, "owner": None}


def _pick_leg(airports, plane_lat, plane_lon):
    """Pick the (origin, dest) leg the plane is currently flying.

    `airports` is a list of {iata, lat, lon}. For a 2-stop route that's the
    only leg. For multi-leg routes we choose the consecutive pair whose
    corridor the plane is closest to (smallest detour through the plane).
    Returns (origin, dest) dicts or None.
    """
    pts = [a for a in airports
           if a.get("iata") and a.get("lat") is not None and a.get("lon") is not None]
    if len(pts) < 2:
        return None
    if plane_lat is None or plane_lon is None:
        return pts[0], pts[-1]
    best = None
    best_cost = None
    for i in range(len(pts) - 1):
        a, b = pts[i], pts[i + 1]
        direct = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
        via = (haversine_km(a["lat"], a["lon"], plane_lat, plane_lon)
               + haversine_km(plane_lat, plane_lon, b["lat"], b["lon"]))
        cost = via - direct  # 0 when the plane is exactly on this leg
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best = (a, b)
    return best


class AircraftEnricher:
    def __init__(self, requests_session):
        self._requests = requests_session
        self._airline_cache = {}
        self._route_cache = {}     # callsign -> list of {iata, lat, lon}
        self._aircraft_cache = {}

    def _get_json(self, url):
        """GET a URL and return parsed JSON dict, or None on any problem."""
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

    def _airline(self, callsign):
        if callsign in self._airline_cache:
            return self._airline_cache[callsign]
        name = None
        data = self._get_json(ADSBDB_CALLSIGN.format(callsign))
        try:
            name = data["response"]["flightroute"]["airline"]["name"]
        except (TypeError, KeyError, AttributeError):
            pass
        self._cache_put(self._airline_cache, callsign, name)
        return name

    def _route_airports(self, callsign):
        if callsign in self._route_cache:
            return self._route_cache[callsign]
        airports = []
        if len(callsign) >= 2:
            data = self._get_json(VRS_ROUTE.format(callsign[:2], callsign))
            try:
                for ap in data["_airports"]:
                    airports.append({
                        "iata": ap.get("iata") or ap.get("icao"),
                        "lat": ap.get("lat"),
                        "lon": ap.get("lon"),
                    })
            except (TypeError, KeyError, AttributeError):
                pass
        self._cache_put(self._route_cache, callsign, airports)
        return airports

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

        `plane_lat`/`plane_lon` let us pick the right leg of a multi-leg route.
        Any field may be None; all lookups are cached and best-effort.
        """
        merged = dict(EMPTY)
        if callsign:
            merged["airline"] = self._airline(callsign)
            leg = _pick_leg(self._route_airports(callsign), plane_lat, plane_lon)
            if leg:
                origin, dest = leg
                merged["origin"] = origin["iata"]
                merged["dest"] = dest["iata"]
                merged["o_lat"] = origin["lat"]
                merged["o_lon"] = origin["lon"]
                merged["d_lat"] = dest["lat"]
                merged["d_lon"] = dest["lon"]
        if icao24:
            merged.update(self._aircraft(icao24))
        return merged
