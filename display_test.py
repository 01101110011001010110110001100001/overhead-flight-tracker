# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# A screen check with no internet needed -- no Wi-Fi, no accounts, no settings.
#
# Run it to make sure the panel is wired right and the text looks good before you
# bother with Wi-Fi and API keys. Copy this onto the CIRCUITPY drive as "code.py"
# (or type `import display_test` in the REPL). It loops through some fake planes,
# the clock, and the status screens using the same code the real app uses.

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

    # Sample FlightAware "route" data (offline; no network). Demonstrates the
    # layout: departure>destination / aircraft type / distance.
    demos = [
        # Full route+type, super close (<= 3 mi) -> RED.
        ({"state": make_state("AAL2487", 40.720, -74.003, 3048.0, vertical_rate=4.0),
          "distance_km": 3.2},
         {"origin": "DFW", "dest": "STL", "type": "A319"}),
        # Full route+type, farther away -> white.
        ({"state": make_state("SWA4048", 40.735, -74.010, 10668.0, vertical_rate=-3.0),
          "distance_km": 12.9},
         {"origin": "TPA", "dest": "STL", "type": "B738"}),
        # No FlightAware data (budget off / unknown flight) -> callsign + altitude.
        ({"state": make_state("N512WT", 40.700, -74.050, 1524.0),
          "distance_km": 20.0},
         None),
    ]

    while True:
        # 1) Flights: three centered lines -- route(or callsign) / type(or alt) /
        #    distance. Red only when nearly overhead (<= 3 mi).
        for flight, route in demos:
            shown = ff.format_flight_lines(flight, route,
                                           units="imperial", close_km=4.8)
            print("Flight: {} | {} | {}".format(
                shown["line1"], shown["line2"], shown["line3"]))
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
