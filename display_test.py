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


def make_state(callsign, lat, lon, baro, on_ground=False, time_position=NOW,
               vertical_rate=0.0):
    """Build an OpenSky-style state vector (see flight_filter index constants)."""
    state = [None] * 17
    state[ff.CALLSIGN] = callsign
    state[ff.TIME_POSITION] = time_position
    state[ff.LONGITUDE] = lon
    state[ff.LATITUDE] = lat
    state[ff.BARO_ALTITUDE] = baro
    state[ff.ON_GROUND] = on_ground
    state[ff.VERTICAL_RATE] = vertical_rate
    return state


# A handful of sample aircraft near "home". Vertical rates exercise the
# climb (^) / descend (v) arrows; distances exercise the proximity color.
SAMPLE_STATES = [
    make_state("UAL245", 40.720, -74.003, 3048.0, vertical_rate=5.0),   # climbing, close
    make_state("DAL1180", 40.735, -74.010, 6096.0, vertical_rate=-4.0), # descending
    make_state("N512WT", 40.700, -74.050, 1524.0, vertical_rate=0.0),   # level
    make_state("", 40.730, -74.000, 2438.0),                            # missing callsign
    make_state("FDX88", 40.690, -73.990, None),                         # missing altitude
]

# Fixed sample UTC time so the clock demo needs no network/clock.
SAMPLE_UTC = 1_751_651_640  # 2025-07-04, afternoon Central


def main():
    print("Display test starting -- no network required.")
    display = build_display()
    ui = FlightDisplay(display, brightness=0.3)  # dimmed; see BRIGHTNESS setting

    # Boot splash (same as the real app).
    ui.show_splash("NELA'S", "SKYWATCH")
    time.sleep(3)

    # Sample adsbdb-style enrichment for the demo (offline; no network).
    # Each entry pairs a flight with airline/route/type so we can show the real
    # layout: airline / route / type+distance.
    demos = [
        ({"state": make_state("EDV4648", 40.720, -74.003, 9448.0),
          "distance_km": 12.9, "radius_km": 40.0},
         {"airline": "Endeavor Air", "origin": "LEX", "dest": "ATL",
          "type": "CRJ9", "registration": "N304PQ", "owner": None}),
        ({"state": make_state("SWA1180", 40.735, -74.010, 3048.0),
          "distance_km": 3.2, "radius_km": 40.0},
         {"airline": "Southwest Airlines", "origin": "STL", "dest": "MDW",
          "type": "B738", "registration": None, "owner": None}),
        # General-aviation plane: no route -> falls back to owner + registration.
        ({"state": make_state("N512WT", 40.700, -74.050, 1524.0),
          "distance_km": 20.0, "radius_km": 40.0},
         {"airline": None, "origin": None, "dest": None,
          "type": "C172", "registration": "N512WT", "owner": "Spirit Flying Club"}),
    ]

    while True:
        # 1) Show enriched flights: airline / route / type+distance.
        #    Color warms as the plane gets closer.
        for flight, enrichment in demos:
            shown = ff.format_enriched_flight(flight, enrichment, units="imperial")
            print("Flight: {} | {} | {} color={:#08x}".format(
                shown["line1"], shown["line2"], shown["line3"], shown["color"]))
            ui.show_flight(shown["line1"], shown["line2"], shown["line3"],
                           color=shown["color"])
            time.sleep(4)

        # 3) Clock fallback (shown instead of "NO FLIGHTS" in the real app).
        shown = clock.format_central_clock(SAMPLE_UTC)
        date_text = clock.format_central_date(SAMPLE_UTC)
        print("Clock:", shown["time"], date_text)
        ui.show_clock(shown["time"], "ST LOUIS", date_text)
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
