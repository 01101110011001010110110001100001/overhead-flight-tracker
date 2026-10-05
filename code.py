# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Overhead flight tracker -- main program for the Adafruit MatrixPortal S3
# driving one 64x32 HUB75 panel. Shows the closest airborne aircraft near your
# home using the OpenSky Network API.
#
# OpenSky detects aircraft near home and provides their positions/distance;
# FlightAware fills in departure airport, destination airport, and aircraft type
# for each newly detected flight (cached, budget-limited).
#
# Structure:
#   flight_display.py -- the panel (hardware)
#   flight_filter.py  -- which plane to show + unit formatting (pure logic)
#   opensky.py        -- OpenSky OAuth2 + positions (network)
#   flightaware.py    -- FlightAware route/type lookups (network)
#   budget.py         -- persistent FlightAware spend tracker (NVM)
#   clock.py          -- UTC -> St. Louis time (pure logic)
#   code.py (this)    -- glue: settings, Wi-Fi, main loop, error recovery
#
# All secrets and your home coordinates live in settings.toml (git-ignored).
# See settings.toml.example. This file never prints secrets.

import os
import ssl
import time

import socketpool
import wifi
import adafruit_requests
import adafruit_ntp

from flight_display import build_display, FlightDisplay
import flight_filter as ff
import clock
from opensky import OpenSkyClient, RateLimited, OpenSkyError
from flightaware import FlightAwareClient
from budget import BudgetTracker

# Root CA for FlightAware's API host (aeroapi.flightaware.com uses an SSL.com
# certificate that isn't in CircuitPython's default bundle).
FLIGHTAWARE_CERT_PATH = "/flightaware_ssl_root.pem"


# ----------------------------------------------------------------------------
# Settings helpers. CircuitPython's settings.toml only stores strings & ints,
# so decimals are stored quoted and converted here.
# ----------------------------------------------------------------------------
def getenv_str(name, default=None):
    value = os.getenv(name)
    return value if value is not None else default


def getenv_float(name, default):
    value = os.getenv(name)
    return float(value) if value is not None else default


def getenv_int(name, default):
    value = os.getenv(name)
    return int(value) if value is not None else default


WIFI_SSID = getenv_str("CIRCUITPY_WIFI_SSID")
WIFI_PASSWORD = getenv_str("CIRCUITPY_WIFI_PASSWORD")
CLIENT_ID = getenv_str("OPENSKY_CLIENT_ID")
CLIENT_SECRET = getenv_str("OPENSKY_CLIENT_SECRET")

HOME_LAT = getenv_float("HOME_LAT", 0.0)
HOME_LON = getenv_float("HOME_LON", 0.0)
UNITS = getenv_str("UNITS", "imperial")
SEARCH_RADIUS = getenv_float("SEARCH_RADIUS", 8.0)  # in UNITS
CLOSE_RADIUS = getenv_float("CLOSE_RADIUS", 3.0)    # in UNITS: red if within this
BRIGHTNESS = getenv_float("BRIGHTNESS", 0.3)        # 0.0 (off) .. 1.0 (full)
REFRESH_SECONDS = getenv_int("REFRESH_SECONDS", 30)
STALE_SECONDS = getenv_int("STALE_SECONDS", 60)

# When no aircraft are nearby, optionally show a St. Louis (US Central) clock
# instead of a plain "NO FLIGHTS" message.
CLOCK_FALLBACK = getenv_str("CLOCK_FALLBACK", "true").lower() == "true"
CLOCK_LABEL = getenv_str("CLOCK_LABEL", "ST LOUIS")

# Personal boot splash (shown briefly on startup).
SPLASH_TOP = getenv_str("SPLASH_TOP", "NELA'S")
SPLASH_BOTTOM = getenv_str("SPLASH_BOTTOM", "SKYWATCH")
SPLASH_SECONDS = 2

# FlightAware AeroAPI (optional: without a key, we run OpenSky-only).
FLIGHTAWARE_API_KEY = getenv_str("FLIGHTAWARE_API_KEY", "")
# Total monthly allowance in USD you're willing to use ($5 free + up to $10 paid).
FLIGHTAWARE_BUDGET_USD = getenv_float("FLIGHTAWARE_BUDGET_USD", 15.0)
# Estimated USD per /flights/{ident} query (1 result set). Confirm the exact
# figure in your AeroAPI dashboard; default is deliberately conservative (high).
FLIGHTAWARE_COST_PER_QUERY = getenv_float("FLIGHTAWARE_COST_PER_QUERY", 0.012)
# Safety margin left unspent below the budget.
FLIGHTAWARE_MARGIN_USD = getenv_float("FLIGHTAWARE_MARGIN_USD", 0.50)

# Treat an empty or still-placeholder key as "no key".
if FLIGHTAWARE_API_KEY and FLIGHTAWARE_API_KEY.startswith("your-"):
    FLIGHTAWARE_API_KEY = ""

# Convert the user's radius (miles or km) into km for the math.
if UNITS == "metric":
    RADIUS_KM = SEARCH_RADIUS
    CLOSE_KM = CLOSE_RADIUS
else:
    RADIUS_KM = SEARCH_RADIUS * ff.KM_PER_MILE
    CLOSE_KM = CLOSE_RADIUS * ff.KM_PER_MILE

# Precompute the API bounding box once (home doesn't move).
BBOX = ff.bbox_around(HOME_LAT, HOME_LON, RADIUS_KM)

# Backoff bounds (seconds) for repeated failures, so we never hammer the network.
BACKOFF_START = 5
BACKOFF_MAX = 300


# ----------------------------------------------------------------------------
# Wi-Fi
# ----------------------------------------------------------------------------
def connect_wifi(ui):
    """Connect to Wi-Fi, retrying with backoff. Returns when connected."""
    delay = BACKOFF_START
    while True:
        try:
            ui.show_status("CONNECTING", "to Wi-Fi...")
            print("Connecting to Wi-Fi SSID:", WIFI_SSID)
            wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
            print("Wi-Fi connected:", wifi.radio.ipv4_address)
            return
        except Exception as error:  # noqa: BLE001 -- show + retry anything
            print("Wi-Fi connect failed:", error)
            ui.show_status("WIFI ERROR", "retrying", "in {}s".format(delay),
                           is_error=True)
            time.sleep(delay)
            delay = min(delay * 2, BACKOFF_MAX)


# ----------------------------------------------------------------------------
# Time source for the clock. OpenSky stamps each response with a UTC time; we
# anchor to it and extrapolate with the board's monotonic timer, so no RTC is
# needed. `time_ref["utc"]` is None until the first successful response.
# ----------------------------------------------------------------------------
def current_utc(time_ref):
    if time_ref["utc"] is None:
        return None
    # IMPORTANT: compute the elapsed seconds as a SMALL number first, convert to
    # int, THEN add to the integer epoch. CircuitPython floats are single
    # precision (24-bit mantissa), so adding a few seconds directly to a ~1.79e9
    # epoch in float loses ~128 s of resolution -- which made the clock freeze in
    # ~2-minute steps and drift. Integer addition of a small delta avoids that.
    elapsed = int(time.monotonic() - time_ref["mono"])
    return time_ref["utc"] + elapsed


NTP_RESYNC_SECONDS = 3600  # re-sync the clock from NTP at most once an hour
SPEND_LOG_SECONDS = 3600   # log the FlightAware spend estimate at most hourly


def sync_time_from_ntp(time_ref, ntp):
    """Anchor the clock to accurate NTP time, at most once an hour.

    Between syncs the clock advances via current_utc()'s integer monotonic
    extrapolation; the hourly re-sync just corrects any slow drift (and avoids a
    network round-trip every loop). Best-effort: on failure we keep the last good
    anchor, and if NTP never works we fall back to OpenSky's response timestamp."""
    if ntp is None:
        return
    now_mono = time.monotonic()
    last = time_ref.get("ntp_sync_mono")
    if time_ref.get("ntp_ok") and last is not None and (now_mono - last) < NTP_RESYNC_SECONDS:
        return  # synced recently; let current_utc() tick via monotonic
    try:
        dt = ntp.datetime  # UTC struct_time (tz_offset=0)
        time_ref["utc"] = clock.utc_from_components(
            dt.tm_year, dt.tm_mon, dt.tm_mday, dt.tm_hour, dt.tm_min, dt.tm_sec)
        time_ref["mono"] = time.monotonic()
        time_ref["ntp_ok"] = True
        time_ref["ntp_sync_mono"] = now_mono
    except Exception as error:  # noqa: BLE001 -- NTP blocked/unreachable
        print("NTP sync failed (will fall back to OpenSky time):", error)


def render_clock(ui, utc):
    shown = clock.format_central_clock(utc)
    ui.show_clock(shown["time"], CLOCK_LABEL, clock.format_central_date(utc))


def sleep_and_render(ui, seconds, view, time_ref):
    """Wait `seconds`, animating the current view.

    `view` is {"kind": "clock"} (re-render the live clock each second) or
    {"kind": "static"} (a flight or message that doesn't change while we wait).
    """
    end = time.monotonic() + seconds
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        if view["kind"] == "clock":
            utc = current_utc(time_ref)
            if utc is not None:
                render_clock(ui, utc)
        time.sleep(1 if remaining > 1 else remaining)


# ----------------------------------------------------------------------------
# One refresh: fetch -> filter -> render. Returns a "view" descriptor that tells
# the wait loop what to animate. Raises on network/API failure.
# ----------------------------------------------------------------------------
def refresh_once(client, fa_client, budget, ui, time_ref):
    report_time, states = client.get_states(BBOX)
    # Only use OpenSky's timestamp for the clock if NTP isn't available (NTP is
    # accurate to the second; OpenSky's timestamp lags a few seconds).
    if report_time is not None and not time_ref.get("ntp_ok"):
        time_ref["utc"] = report_time
        time_ref["mono"] = time.monotonic()

    # Roll the FlightAware budget into the current billing month once we know it.
    utc = current_utc(time_ref)
    if budget is not None and utc is not None:
        budget.set_month(clock.utc_month_id(utc))

    result = ff.select_closest(
        states, HOME_LAT, HOME_LON, RADIUS_KM,
        now=report_time, max_age_s=STALE_SECONDS)

    flight = result["flight"]
    if flight is not None:
        state = flight["state"]
        callsign = (ff._get(state, ff.CALLSIGN) or "").strip()
        icao24 = ff._get(state, ff.ICAO24)
        # FlightAware route/type for THIS aircraft (cached per icao24; a given
        # plane is looked up at most once). None when FA is off/out of budget.
        route = fa_client.lookup(icao24, callsign) if fa_client else None
        shown = ff.format_flight_lines(flight, route, units=UNITS,
                                       close_km=CLOSE_KM)
        print("Closest:", shown["line1"], "|", shown["line2"], "|", shown["line3"])
        ui.show_flight(shown["line1"], shown["line2"], shown["line3"],
                       color=shown["color"])
        return {"kind": "static"}

    if result["stale_only"]:
        # We DID reach the API and saw nearby planes, but their fixes were old.
        print("Nearby aircraft seen, but positions are stale.")
        ui.show_status("STALE DATA", "waiting for", "fresh fix")
        return {"kind": "static"}

    # No eligible aircraft: show the clock if enabled and we know the time.
    utc = current_utc(time_ref)
    if CLOCK_FALLBACK and utc is not None:
        shown = clock.format_central_clock(utc)
        src = "NTP" if time_ref.get("ntp_ok") else "OpenSky"
        print("No flights; clock {} {} (time src: {})".format(
            shown["time"], shown["abbr"], src))
        render_clock(ui, utc)
        return {"kind": "clock"}

    print("No eligible aircraft within radius.")
    ui.show_status("NO FLIGHTS", "nearby")
    return {"kind": "static"}


def main():
    display = build_display()
    ui = FlightDisplay(display, brightness=BRIGHTNESS)

    # Personal boot splash.
    ui.show_splash(SPLASH_TOP, SPLASH_BOTTOM)
    time.sleep(SPLASH_SECONDS)

    # Credentials missing? Stay in a safe, obvious state instead of crashing.
    if not WIFI_SSID or not CLIENT_ID or not CLIENT_SECRET:
        print("Missing Wi-Fi or OpenSky credentials in settings.toml.")
        ui.show_status("SETUP NEEDED", "edit", "settings.toml", is_error=True)
        while True:
            time.sleep(60)

    connect_wifi(ui)

    pool = socketpool.SocketPool(wifi.radio)
    # OpenSky uses a Let's Encrypt cert, covered by CircuitPython's default bundle.
    context = ssl.create_default_context()
    requests_session = adafruit_requests.Session(pool, context)
    client = OpenSkyClient(requests_session, CLIENT_ID, CLIENT_SECRET)

    # FlightAware: optional. Its API host uses an SSL.com cert that the default
    # bundle doesn't include, so give it a SEPARATE context loaded with that root.
    fa_client = None
    budget = None
    if FLIGHTAWARE_API_KEY:
        budget = BudgetTracker(FLIGHTAWARE_COST_PER_QUERY, FLIGHTAWARE_BUDGET_USD,
                               FLIGHTAWARE_MARGIN_USD)
        try:
            fa_context = ssl.create_default_context()
            with open(FLIGHTAWARE_CERT_PATH, "r") as certfile:
                fa_context.load_verify_locations(cadata=certfile.read())
            fa_session = adafruit_requests.Session(pool, fa_context)
            fa_client = FlightAwareClient(fa_session, FLIGHTAWARE_API_KEY, budget)
            print("FlightAware enabled. Est. spent this month: ${:.2f} of ${:.2f}".format(
                budget.spent_usd(), budget.hard_limit))
        except OSError:
            print("FlightAware root cert missing ({}); OpenSky-only.".format(
                FLIGHTAWARE_CERT_PATH))
            fa_client = None
    else:
        print("No FlightAware key set; OpenSky-only (no route/type).")

    # Accurate time from an NTP server (UTC). cache_seconds=0 so each (hourly)
    # sync_time_from_ntp() call does a fresh query; our own timer limits how often.
    ntp = adafruit_ntp.NTP(pool, tz_offset=0)

    # Clock anchor: NTP when available, else OpenSky's response timestamp.
    time_ref = {"utc": None, "mono": 0.0, "ntp_ok": False}

    last_spend_log = None  # monotonic time of the last hourly spend report

    backoff = BACKOFF_START
    while True:
        wait = REFRESH_SECONDS
        view = {"kind": "static"}
        try:
            # If Wi-Fi dropped, reconnect before trying the API.
            if not wifi.radio.connected:
                print("Wi-Fi dropped; reconnecting.")
                connect_wifi(ui)

            sync_time_from_ntp(time_ref, ntp)  # keep the clock accurate

            # Report estimated FlightAware spend once an hour (and on first loop).
            if budget is not None:
                now_mono = time.monotonic()
                if last_spend_log is None or (now_mono - last_spend_log) >= SPEND_LOG_SECONDS:
                    print("FlightAware budget: est. ${:.2f} of ${:.2f} spent this "
                          "month ({} queries)".format(
                              budget.spent_usd(), budget.hard_limit, budget.count))
                    last_spend_log = now_mono

            view = refresh_once(client, fa_client, budget, ui, time_ref)
            backoff = BACKOFF_START  # success resets the backoff

        except RateLimited as limited:
            # Respect the server's instruction; never retry faster than asked.
            wait = limited.retry_after or BACKOFF_MAX
            print("Rate limited; waiting {}s.".format(wait))
            ui.show_status("RATE LIMIT", "waiting", "{}s".format(wait),
                           is_error=True)

        except OpenSkyError as api_error:
            print("API error:", api_error)
            ui.show_status("API ERROR", "retrying", "in {}s".format(backoff),
                           is_error=True)
            wait = backoff
            backoff = min(backoff * 2, BACKOFF_MAX)

        except Exception as error:  # noqa: BLE001 -- e.g. transient socket error
            print("Network error:", error)
            ui.show_status("NO SIGNAL", "retrying", "in {}s".format(backoff),
                           is_error=True)
            wait = backoff
            backoff = min(backoff * 2, BACKOFF_MAX)

        # Wait until the next refresh, animating the current view (clock ticks,
        # big flight view rotates between airports and type/distance).
        sleep_and_render(ui, wait, view, time_ref)


main()
