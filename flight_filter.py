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
ICAO24 = 0          # str, lowercase hex Mode-S address (used for type lookup)
CALLSIGN = 1        # str, may be None or padded with spaces
TIME_POSITION = 3   # int Unix seconds of last position update, may be None
LONGITUDE = 5       # float degrees WGS-84, may be None
LATITUDE = 6        # float degrees WGS-84, may be None
BARO_ALTITUDE = 7   # float meters, may be None
ON_GROUND = 8       # bool
VERTICAL_RATE = 11  # float m/s: + climbing, - descending, may be None
GEO_ALTITUDE = 13   # float meters, may be None (fallback for altitude)

# --- Unit conversion factors ---------------------------------------------
FEET_PER_METER = 3.28084
MILES_PER_KM = 0.621371
KM_PER_MILE = 1.609344
EARTH_RADIUS_KM = 6371.0

# --- Proximity color gradient (0xRRGGBB) ---------------------------------
# A plane glows green when it's far out, warms through amber, and turns red as
# it comes nearly overhead -- so you can read "how close" at a glance.
PROX_FAR = 0x00CC33   # green  (at/near the radius edge)
PROX_MID = 0xFFAA00   # amber  (about halfway in)
PROX_NEAR = 0xFF2222  # red    (right on top of you)

# Vertical-rate threshold (m/s) below which we call the aircraft "level".
LEVEL_RATE = 0.5


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
        flight = {"state": best, "distance_km": best_dist, "radius_km": radius_km}

    return {"flight": flight, "stale_only": (flight is None and saw_stale)}


def scale_color(color, scale):
    """Dim a 0xRRGGBB color by `scale` (0.0=off .. 1.0=full). Reduces glare."""
    scale = min(1.0, max(0.0, scale))
    r = int(round(((color >> 16) & 0xFF) * scale))
    g = int(round(((color >> 8) & 0xFF) * scale))
    b = int(round((color & 0xFF) * scale))
    return (r << 16) | (g << 8) | b


def _blend(color_a, color_b, t):
    """Linearly blend two 0xRRGGBB colors. t=0 -> a, t=1 -> b."""
    t = min(1.0, max(0.0, t))
    ar, ag, ab = (color_a >> 16) & 0xFF, (color_a >> 8) & 0xFF, color_a & 0xFF
    br, bg, bb = (color_b >> 16) & 0xFF, (color_b >> 8) & 0xFF, color_b & 0xFF
    r = int(round(ar + (br - ar) * t))
    g = int(round(ag + (bg - ag) * t))
    b = int(round(ab + (bb - ab) * t))
    return (r << 16) | (g << 8) | b


def proximity_color(distance_km, radius_km):
    """Color for a flight based on how close it is: green (far) -> red (near)."""
    if radius_km <= 0:
        return PROX_NEAR
    ratio = min(1.0, max(0.0, distance_km / radius_km))  # 1=far edge, 0=overhead
    if ratio >= 0.5:
        # Outer half: green -> amber as it crosses from the edge to halfway.
        return _blend(PROX_FAR, PROX_MID, (1.0 - ratio) / 0.5)
    # Inner half: amber -> red as it closes in.
    return _blend(PROX_MID, PROX_NEAR, (0.5 - ratio) / 0.5)


def _climb_arrow(state):
    """'^' climbing, 'v' descending, '' level/unknown. ASCII for font safety."""
    rate = _get(state, VERTICAL_RATE)
    if rate is None:
        return ""
    if rate > LEVEL_RATE:
        return " ^"
    if rate < -LEVEL_RATE:
        return " v"
    return ""


def format_flight(flight, units="imperial"):
    """Turn a selected flight into short display strings + a color.

    Handles missing callsigns and missing altitude gracefully. Returns a dict:
      callsign, altitude (with a climb/descent arrow), distance, and color
      (0xRRGGBB chosen by proximity).
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
    # radius_km is present on dicts from select_closest; fall back to the
    # distance (ratio 1.0 -> far/green) if a caller built the dict by hand.
    radius_km = flight.get("radius_km", distance_km)
    arrow = _climb_arrow(state)

    if units == "metric":
        if altitude_m is None:
            altitude = "ALT --"
        else:
            altitude = "{} m{}".format(int(round(altitude_m)), arrow)
        distance = "{:.1f} km".format(distance_km)
    else:  # imperial
        if altitude_m is None:
            altitude = "ALT --"
        else:
            altitude = "{} ft{}".format(
                int(round(altitude_m * FEET_PER_METER)), arrow)
        distance = "{:.1f} mi".format(distance_km * MILES_PER_KM)

    return {
        "callsign": callsign,
        "altitude": altitude,
        "distance": distance,
        "color": proximity_color(distance_km, radius_km),
    }


# Longest string that fits one line of the 6px font on a 64px-wide panel.
MAX_LINE = 10


def _truncate(text, limit=MAX_LINE):
    return text if len(text) <= limit else text[:limit]


def _airline_short(name):
    """Fit an airline name on one line: whole name if it fits, else first word."""
    if len(name) <= MAX_LINE:
        return name
    return name.split(" ")[0][:MAX_LINE]


def _compact_distance(distance_km, units):
    """Short distance for the type line, e.g. '8mi' or '8km' (no decimals)."""
    if units == "metric":
        return "{:.0f}km".format(distance_km)
    return "{:.0f}mi".format(distance_km * MILES_PER_KM)


def format_enriched_flight(flight, enrichment, units="imperial"):
    """Build the 3 display lines from a flight + adsbdb enrichment.

    Layout: airline / route / type+distance. Degrades gracefully:
      * no airline  -> owner, else callsign
      * no route    -> registration, else '--'
      * no type     -> just the distance
    Returns {line1, line2, line3, color}.
    """
    state = flight["state"]
    callsign = (_get(state, CALLSIGN) or "").strip() or "UNKNOWN"
    enr = enrichment or {}

    # Line 1 -- airline, else owner, else callsign.
    if enr.get("airline"):
        line1 = _airline_short(enr["airline"])
    elif enr.get("owner"):
        line1 = _truncate(enr["owner"])
    else:
        line1 = _truncate(callsign)

    # Line 2 -- route (origin>dest), else registration, else placeholder.
    if enr.get("origin") and enr.get("dest"):
        line2 = _truncate("{}>{}".format(enr["origin"], enr["dest"]))
    elif enr.get("registration"):
        line2 = _truncate(enr["registration"])
    else:
        line2 = "--"

    # Line 3 -- aircraft type + compact distance (distance right-aligned-ish).
    distance_km = flight["distance_km"]
    radius_km = flight.get("radius_km", distance_km)
    dist = _compact_distance(distance_km, units)
    if enr.get("type"):
        room = max(1, MAX_LINE - len(dist) - 1)  # leave a space before distance
        line3 = "{} {}".format(_truncate(enr["type"], room), dist)
    else:
        line3 = dist

    return {
        "line1": line1,
        "line2": line2,
        "line3": line3,
        "color": proximity_color(distance_km, radius_km),
    }
