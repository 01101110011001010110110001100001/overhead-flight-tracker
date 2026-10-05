# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Overhead flight tracker -- main program for the Adafruit MatrixPortal S3
# driving one 64x32 HUB75 panel. Shows the closest airborne aircraft near your
# home using the OpenSky Network API.
#
# Structure:
#   flight_display.py -- the panel (hardware)
#   flight_filter.py  -- which plane to show + unit formatting (pure logic)
#   opensky.py        -- OAuth2 + API calls (network)
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

from flight_display import build_display, FlightDisplay
import flight_filter as ff
import clock
from opensky import OpenSkyClient, RateLimited, OpenSkyError


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

# Convert the user's radius (miles or km) into km for the math.
if UNITS == "metric":
    RADIUS_KM = SEARCH_RADIUS
else:
    RADIUS_KM = SEARCH_RADIUS * ff.KM_PER_MILE

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
    return int(time_ref["utc"] + (time.monotonic() - time_ref["mono"]))


def render_clock(ui, utc):
    shown = clock.format_central_clock(utc)
    ui.show_clock(shown["time"], CLOCK_LABEL, clock.format_central_date(utc))


def sleep_with_clock(ui, seconds, clock_active, time_ref):
    """Wait `seconds`, re-rendering the clock each second if it's showing."""
    end = time.monotonic() + seconds
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        if clock_active:
            utc = current_utc(time_ref)
            if utc is not None:
                render_clock(ui, utc)
        time.sleep(1 if remaining > 1 else remaining)


# ----------------------------------------------------------------------------
# One refresh: fetch -> filter -> render. Returns True if the clock fallback is
# now showing (so the caller keeps it ticking). Raises on network/API failure.
# ----------------------------------------------------------------------------
def refresh_once(client, ui, time_ref):
    report_time, states = client.get_states(BBOX)
    if report_time is not None:
        # Anchor our clock to OpenSky's UTC timestamp.
        time_ref["utc"] = report_time
        time_ref["mono"] = time.monotonic()

    result = ff.select_closest(
        states, HOME_LAT, HOME_LON, RADIUS_KM,
        now=report_time, max_age_s=STALE_SECONDS)

    flight = result["flight"]
    if flight is not None:
        shown = ff.format_flight(flight, units=UNITS)
        print("Closest:", shown["callsign"], shown["altitude"], shown["distance"])
        ui.show_flight(shown["callsign"], shown["altitude"], shown["distance"],
                       color=shown["color"])
        return False

    if result["stale_only"]:
        # We DID reach the API and saw nearby planes, but their fixes were old.
        print("Nearby aircraft seen, but positions are stale.")
        ui.show_status("STALE DATA", "waiting for", "fresh fix")
        return False

    # No eligible aircraft: show the clock if enabled and we know the time.
    utc = current_utc(time_ref)
    if CLOCK_FALLBACK and utc is not None:
        print("No flights nearby; showing clock.")
        render_clock(ui, utc)
        return True

    print("No eligible aircraft within radius.")
    ui.show_status("NO FLIGHTS", "nearby")
    return False


def main():
    display = build_display()
    ui = FlightDisplay(display)

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
    # Modern CircuitPython bundles Mozilla CA roots, so the default SSL context
    # trusts opensky-network.org without shipping a .pem file.
    context = ssl.create_default_context()
    requests_session = adafruit_requests.Session(pool, context)
    client = OpenSkyClient(requests_session, CLIENT_ID, CLIENT_SECRET)

    # Clock anchor: filled in from OpenSky's response timestamp on first success.
    time_ref = {"utc": None, "mono": 0.0}

    backoff = BACKOFF_START
    while True:
        wait = REFRESH_SECONDS
        clock_active = False
        try:
            # If Wi-Fi dropped, reconnect before trying the API.
            if not wifi.radio.connected:
                print("Wi-Fi dropped; reconnecting.")
                connect_wifi(ui)

            clock_active = refresh_once(client, ui, time_ref)
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

        # Wait until the next refresh. If the clock is showing, keep it live.
        sleep_with_clock(ui, wait, clock_active, time_ref)


main()
