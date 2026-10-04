# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# DISPLAY-ONLY TEST -- no Wi-Fi, no OpenSky account, no settings.toml needed.
#
# Purpose: prove your 64x32 panel is wired and configured correctly, and that
# the rendering/formatting pipeline looks right, BEFORE involving the network.
#
# HOW TO RUN ON THE BOARD:
#   Copy this file onto the CIRCUITPY drive AS "code.py" (overwriting the real
#   one), or in the REPL run:  import display_test
# It cycles through sample aircraft and every status screen, forever.
#
# It uses the SAME modules as the real app (flight_display + flight_filter), so
# a good-looking test means those pieces work.

import time

from flight_display import build_display, FlightDisplay
import flight_filter as ff
import clock

# Pretend "home" is Manhattan for this demo.
HOME_LAT = 40.7128
HOME_LON = -74.0060
NOW = 10_000  # a fake "current time" for staleness math


def make_state(callsign, lat, lon, baro, on_ground=False, time_position=NOW):
    """Build an OpenSky-style state vector (see flight_filter index constants)."""
    state = [None] * 17
    state[ff.CALLSIGN] = callsign
    state[ff.TIME_POSITION] = time_position
    state[ff.LONGITUDE] = lon
    state[ff.LATITUDE] = lat
    state[ff.BARO_ALTITUDE] = baro
    state[ff.ON_GROUND] = on_ground
    return state


# A handful of sample aircraft near "home".
SAMPLE_STATES = [
    make_state("UAL245", 40.720, -74.003, 3048.0),   # ~10,000 ft, closest
    make_state("DAL1180", 40.735, -74.010, 6096.0),  # ~20,000 ft
    make_state("N512WT", 40.700, -74.050, 1524.0),   # small plane, ~5,000 ft
    make_state("", 40.730, -74.000, 2438.0),          # missing callsign
    make_state("FDX88", 40.690, -73.990, None),       # missing altitude
]


def main():
    print("Display test starting -- no network required.")
    display = build_display()
    ui = FlightDisplay(display)

    while True:
        # 1) Show the closest aircraft picked from the sample set, both units.
        for units in ("imperial", "metric"):
            result = ff.select_closest(
                SAMPLE_STATES, HOME_LAT, HOME_LON,
                radius_km=15, now=NOW, max_age_s=60)
            flight = ff.format_flight(result["flight"], units=units)
            print("Closest ({}): {} {} {}".format(
                units, flight["callsign"], flight["altitude"], flight["distance"]))
            ui.show_flight(flight["callsign"], flight["altitude"], flight["distance"])
            time.sleep(4)

        # 2) Show a flight with a missing callsign / missing altitude explicitly.
        odd = ff.format_flight(
            {"state": make_state("", 40.715, -74.005, None), "distance_km": 2.0},
            units="imperial")
        ui.show_flight(odd["callsign"], odd["altitude"], odd["distance"])
        time.sleep(4)

        # 3) Clock fallback (shown instead of "NO FLIGHTS" in the real app).
        #    Uses a fixed sample UTC time so no network/clock is needed here.
        sample_utc = 1_751_651_640  # 2025-07-04, afternoon Central
        shown = clock.format_central_clock(sample_utc)
        print("Clock:", shown["time"], shown["abbr"])
        ui.show_clock(shown["time"], "ST LOUIS", shown["abbr"])
        time.sleep(4)

        # 4) Cycle through every status screen the real app can show.
        ui.show_status("CONNECTING", "to Wi-Fi...")
        time.sleep(3)
        ui.show_status("NO FLIGHTS", "nearby", "(all clear)")
        time.sleep(3)
        ui.show_status("STALE DATA", "waiting for", "fresh fix")
        time.sleep(3)
        ui.show_status("WIFI ERROR", "retrying...", is_error=True)
        time.sleep(3)
        ui.show_status("API ERROR", "retrying...", is_error=True)
        time.sleep(3)


main()
