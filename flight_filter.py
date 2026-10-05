# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# The "which plane, and how do we show it" logic: distances, filtering, and
# formatting the lines of text. It's plain math with no hardware or network, so
# it runs on a normal computer and is covered by tests/test_flight_filter.py.
#
# OpenSky hands us each plane as a plain list ("state vector"); the constants
# below name the slots we care about. Full list:
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

# --- Flight colors (0xRRGGBB) --------------------------------------------
# Neutral by default: plain white. The only accent is red, shown only when a
# plane is "super close" (within close_km) -- i.e. nearly overhead.
COLOR_NORMAL = 0xFFFFFF   # white: the everyday color
COLOR_CLOSE = 0xFF3333    # red: super close / nearly overhead
DEFAULT_CLOSE_KM = 4.8    # ~3 miles

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


def flight_color(distance_km, close_km=DEFAULT_CLOSE_KM):
    """Neutral white, except red when the plane is within `close_km` (overhead)."""
    return COLOR_CLOSE if distance_km <= close_km else COLOR_NORMAL


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


def _altitude_text(state, units):
    """Altitude with climb/descent arrow, e.g. '35000 ft ^' / '3000 m', or None."""
    altitude_m = _get(state, BARO_ALTITUDE)
    if altitude_m is None:
        altitude_m = _get(state, GEO_ALTITUDE)
    if altitude_m is None:
        return None
    arrow = _climb_arrow(state)
    if units == "metric":
        return "{} m{}".format(int(round(altitude_m)), arrow)
    return "{} ft{}".format(int(round(altitude_m * FEET_PER_METER)), arrow)


def format_flight(flight, units="imperial", close_km=DEFAULT_CLOSE_KM):
    """Turn a selected flight into short display strings + a color.

    Handles missing callsigns and missing altitude gracefully. Returns a dict:
      callsign, altitude (with a climb/descent arrow), distance, and color
      (white, or red when within close_km).
    """
    state = flight["state"]

    raw_callsign = _get(state, CALLSIGN)
    callsign = raw_callsign.strip() if raw_callsign else ""
    if not callsign:
        callsign = "UNKNOWN"

    distance_km = flight["distance_km"]
    altitude = _altitude_text(state, units) or "ALT --"
    if units == "metric":
        distance = "{:.1f} km".format(distance_km)
    else:
        distance = "{:.1f} mi".format(distance_km * MILES_PER_KM)

    return {
        "callsign": callsign,
        "altitude": altitude,
        "distance": distance,
        "color": flight_color(distance_km, close_km),
    }


# Longest string that fits one line of the 6px font on a 64px-wide panel.
MAX_LINE = 10


def _truncate(text, limit=MAX_LINE):
    return text if len(text) <= limit else text[:limit]


# FlightAware gives aircraft types as short ICAO codes (e.g. "BCS1"). Most people
# would rather see the model name ("A220-100"), so we translate the common ones.
# Anything not listed just shows its code, which is still meaningful. Names are
# kept short (<= ~10 chars) to fit the panel.
AIRCRAFT_NAMES = {
    # Airbus
    "A318": "A318", "A319": "A319", "A320": "A320", "A321": "A321",
    "A19N": "A319neo", "A20N": "A320neo", "A21N": "A321neo",
    "A332": "A330-200", "A333": "A330-300", "A339": "A330-900",
    "A342": "A340-200", "A343": "A340-300", "A345": "A340-500", "A346": "A340-600",
    "A359": "A350-900", "A35K": "A350-1K", "A388": "A380",
    "BCS1": "A220-100", "BCS3": "A220-300",
    # Boeing
    "B712": "717-200", "B733": "737-300", "B734": "737-400", "B735": "737-500",
    "B736": "737-600", "B737": "737-700", "B738": "737-800", "B739": "737-900",
    "B38M": "737 MAX8", "B39M": "737 MAX9", "B3XM": "737 MX10",
    "B752": "757-200", "B753": "757-300",
    "B762": "767-200", "B763": "767-300", "B764": "767-400",
    "B772": "777-200", "B77L": "777-200L", "B773": "777-300", "B77W": "777-300ER",
    "B788": "787-8", "B789": "787-9", "B78X": "787-10",
    "B744": "747-400", "B748": "747-8",
    # Embraer
    "E170": "E170", "E75S": "E175", "E75L": "E175", "E175": "E175",
    "E190": "E190", "E195": "E195", "E290": "E190-E2", "E295": "E195-E2",
    # Regional / turboprop
    "CRJ2": "CRJ-200", "CRJ7": "CRJ-700", "CRJ9": "CRJ-900", "CRJX": "CRJ-1000",
    "DH8D": "Q400", "AT72": "ATR 72", "AT76": "ATR72-6", "AT45": "ATR 42",
    # Common general aviation
    "C172": "C172", "C182": "C182", "C208": "C208", "PC12": "PC-12",
    "SR22": "SR22", "BE20": "King Air",
    # Helicopters (news, medical, police, tour, offshore)
    "EC30": "H130", "EC20": "H120", "EC35": "H135", "EC45": "H145",
    "EC75": "H175", "AS50": "AS350", "AS55": "AS355", "EC25": "H225",
    "R22": "R22", "R44": "R44", "R66": "R66",
    "B06": "Bell 206", "B407": "Bell 407", "B412": "Bell 412", "B429": "Bell 429",
    "S76": "S-76", "S92": "S-92", "H500": "MD 500",
    "A109": "AW109", "A139": "AW139", "A169": "AW169",
}


def aircraft_name(code):
    """Friendly model name for an ICAO type code, or the code itself if unknown."""
    if not code:
        return None
    return AIRCRAFT_NAMES.get(code.upper(), code)


# Callsign keywords that reveal what an aircraft is doing. Lots of special-use
# aircraft broadcast a telephony callsign that says it outright: an air
# ambulance really does transmit "MEDEVAC" or "LIFEGUARD", a news helicopter
# "CHOPPER4", a police unit "POLICE1", and so on. We use these as a best-effort
# guess for flights with no filed route (helicopters and little planes rarely
# file one). First keyword found wins, so list the strongest signals first.
# Labels stay <= MAX_LINE characters so they fit on one line.
OPERATION_KEYWORDS = (
    # Air medical / ambulance (LIFEGUARD is the FAA term for a medical-priority
    # flight; ARCH is St. Louis's own air-ambulance service)
    ("MEDEVAC", "Medical"), ("MEDIC", "Medical"), ("LIFE", "Medical"),
    ("ARCH", "Medical"), ("MERCY", "Medical"), ("ANGEL", "Medical"),
    ("SURVIVAL", "Medical"), ("AIRMED", "Medical"), ("AIRLIFT", "Medical"),
    ("CAREFL", "Medical"), ("STARFL", "Medical"),
    # Law enforcement
    ("POLICE", "Police"), ("SHERIF", "Police"), ("TROOP", "Police"),
    # News / media
    ("CHOPPER", "News"), ("NEWS", "News"),
    # Firefighting
    ("FIRE", "Fire"), ("TANKER", "Fire"), ("HELITAK", "Fire"),
    # Search & rescue / coast guard
    ("RESCUE", "Rescue"), ("COASTGUARD", "Rescue"),
    # Military (usually filtered out already, but just in case)
    ("ARMY", "Military"), ("NAVY", "Military"), ("MARINE", "Military"),
)

# Aircraft types used almost entirely for flight instruction. This is only a
# soft fallback when the callsign says nothing -- it's a guess about the type
# of plane, not proof of what this particular flight is up to.
TRAINER_TYPES = ("R22", "C150", "C152", "DV20", "DA20", "PA38", "P38T")


def guess_operation(callsign, type_code=None):
    """Best-effort guess of what an aircraft is doing, for routeless flights.

    Looks for a telling keyword in the callsign first (reliable -- the aircraft
    is literally announcing it), then falls back to a soft "Training" guess for
    the little trainer types. Returns a short label (<= MAX_LINE chars) or None.
    """
    text = (callsign or "").upper()
    for keyword, label in OPERATION_KEYWORDS:
        if keyword in text:
            return label
    if type_code and type_code.upper() in TRAINER_TYPES:
        return "Training"
    return None


def format_flight_lines(flight, route, units="imperial", close_km=DEFAULT_CLOSE_KM):
    """Build the 3 display lines from an OpenSky flight + FlightAware `route`.

    `route` is {origin, dest, type} from FlightAware, or None when FlightAware
    data isn't available (no key, budget exhausted, unknown flight, API error).
      * line 1 -- departure>destination if known, else the callsign
      * line 2 -- aircraft type if known, else the altitude (climb/descent arrow)
      * line 3 -- distance from home
    Color is white, or red when within close_km (nearly overhead). The distance
    always comes from the latest OpenSky position.
    Returns {line1, line2, line3, color}.
    """
    state = flight["state"]
    callsign = (_get(state, CALLSIGN) or "").strip() or "UNKNOWN"
    route = route or {}
    distance_km = flight["distance_km"]

    # Line 1 -- route (DEP>DEST) if FlightAware gave us both. With no route
    # (common for helicopters and small planes, which rarely file one), guess
    # the mission from the callsign/type -- e.g. "Medical", "News", "Training"
    # -- and fall back to the raw callsign when we can't tell.
    if route.get("origin") and route.get("dest"):
        line1 = _truncate("{}>{}".format(route["origin"], route["dest"]))
    else:
        operation = guess_operation(callsign, route.get("type"))
        line1 = _truncate(operation or callsign)

    # Line 2 -- aircraft model name if known, else altitude.
    type_name = aircraft_name(route.get("type"))
    if type_name:
        line2 = _truncate(type_name)
    else:
        line2 = _altitude_text(state, units) or "ALT --"

    # Line 3 -- distance from home (from the latest OpenSky coordinates).
    if units == "metric":
        line3 = "{:.1f} km".format(distance_km)
    else:
        line3 = "{:.1f} mi".format(distance_km * MILES_PER_KM)

    return {
        "line1": line1,
        "line2": line2,
        "line3": line3,
        "color": flight_color(distance_km, close_km),
    }
