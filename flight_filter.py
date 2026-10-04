# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Pure aircraft-selection logic for the overhead flight tracker.
#
# This module has NO hardware or network dependencies (only `math`), so it runs
# unchanged on a desktop Python and is exercised by tests/test_flight_filter.py.
# Everything that decides "which plane do we show, and how" lives here.
#
# It works on OpenSky "state vectors". A state vector is a plain list; the
# meaning of each slot is fixed by OpenSky's API and captured by the index
# constants below. See:
# https://openskynetwork.github.io/opensky-api/rest.html#response

import math

# --- OpenSky state-vector field indices ----------------------------------
CALLSIGN = 1        # str, may be None or padded with spaces
TIME_POSITION = 3   # int Unix seconds of last position update, may be None
LONGITUDE = 5       # float degrees WGS-84, may be None
LATITUDE = 6        # float degrees WGS-84, may be None
BARO_ALTITUDE = 7   # float meters, may be None
ON_GROUND = 8       # bool
GEO_ALTITUDE = 13   # float meters, may be None (fallback for altitude)

# --- Unit conversion factors ---------------------------------------------
FEET_PER_METER = 3.28084
MILES_PER_KM = 0.621371
KM_PER_MILE = 1.609344
EARTH_RADIUS_KM = 6371.0


def _get(state, index):
    """Safely read a field from a state vector that may be shorter than expected."""
    if state is None or index >= len(state):
        return None
    return state[index]


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle horizontal distance between two lat/lon points, in km."""
    rlat1 = math.radians(lat1)
    rlat2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2)
    c = 2 * math.asin(min(1.0, math.sqrt(a)))
    return EARTH_RADIUS_KM * c


def bbox_around(lat, lon, radius_km):
    """A small lat/lon box around home, sized to the search radius.

    This is only a coarse pre-filter for the API query (so we download few
    aircraft and pay 1 credit); exact distance filtering happens afterward in
    select_closest(). One degree of latitude is ~111 km; longitude degrees
    shrink toward the poles, hence the cos(lat) term.
    """
    dlat = radius_km / 111.0
    # Guard against cos(lat) -> 0 near the poles so we never divide by ~0.
    dlon = radius_km / (111.0 * max(0.01, math.cos(math.radians(lat))))
    return {
        "lamin": lat - dlat,
        "lamax": lat + dlat,
        "lomin": lon - dlon,
        "lomax": lon + dlon,
    }


def select_closest(states, home_lat, home_lon, radius_km,
                   now=None, max_age_s=60):
    """Pick the closest eligible airborne aircraft.

    An aircraft is eligible only if it:
      * has a valid latitude AND longitude (not None),
      * is NOT on the ground,
      * is within `radius_km` of home (exact haversine distance), and
      * has a fresh position: `now - TIME_POSITION <= max_age_s`.

    `now` should be OpenSky's own report timestamp (the top-level "time" field
    of the response) so we don't depend on the board having an accurate clock.
    If `now` is None, the staleness check is skipped.

    Returns a dict:
      {
        "flight": {"state": <state vector>, "distance_km": <float>} or None,
        "stale_only": bool,   # True if the ONLY reason we found nothing was
                              # that every nearby aircraft had a stale position
      }
    `stale_only` lets the caller show "STALE DATA" instead of "NO FLIGHTS".
    """
    best = None
    best_dist = None
    saw_stale = False

    for state in states or []:
        lat = _get(state, LATITUDE)
        lon = _get(state, LONGITUDE)
        if lat is None or lon is None:
            continue  # no valid position -> cannot place or measure it
        if _get(state, ON_GROUND):
            continue  # taxiing / parked, not "overhead"

        distance = haversine_km(home_lat, home_lon, lat, lon)
        if distance > radius_km:
            continue  # outside our radius

        # It's a nearby airborne aircraft with a position. Is that position fresh?
        if now is not None:
            time_pos = _get(state, TIME_POSITION)
            if time_pos is None or (now - time_pos) > max_age_s:
                saw_stale = True
                continue

        if best_dist is None or distance < best_dist:
            best = state
            best_dist = distance

    flight = None
    if best is not None:
        flight = {"state": best, "distance_km": best_dist}

    return {"flight": flight, "stale_only": (flight is None and saw_stale)}


def format_flight(flight, units="imperial"):
    """Turn a selected flight into short display strings.

    Handles missing callsigns and missing altitude gracefully. Returns a dict
    with three ready-to-render strings: callsign, altitude, distance.
    """
    state = flight["state"]

    raw_callsign = _get(state, CALLSIGN)
    callsign = raw_callsign.strip() if raw_callsign else ""
    if not callsign:
        callsign = "UNKNOWN"

    # Prefer barometric altitude; fall back to geometric (GPS) altitude.
    altitude_m = _get(state, BARO_ALTITUDE)
    if altitude_m is None:
        altitude_m = _get(state, GEO_ALTITUDE)

    distance_km = flight["distance_km"]

    if units == "metric":
        if altitude_m is None:
            altitude = "ALT --"
        else:
            altitude = "{} m".format(int(round(altitude_m)))
        distance = "{:.1f} km".format(distance_km)
    else:  # imperial
        if altitude_m is None:
            altitude = "ALT --"
        else:
            altitude = "{} ft".format(int(round(altitude_m * FEET_PER_METER)))
        distance = "{:.1f} mi".format(distance_km * MILES_PER_KM)

    return {"callsign": callsign, "altitude": altitude, "distance": distance}
