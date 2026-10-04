# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Portions adapted from Adafruit's "MatrixPortal S3 Flight Proximity Tracker"
# example (the RGBMatrix pin setup):
#   SPDX-FileCopyrightText: 2023 Trevor Beaton for Adafruit Industries
#   SPDX-License-Identifier: MIT
#   https://learn.adafruit.com/matrixportal-s3-flight-proximity-tracker
#
# Display layer for the overhead flight tracker. Runs ONLY on the board
# (it imports `board`, `rgbmatrix`, etc.). It knows nothing about networking
# or aircraft logic -- it just renders strings onto a 64x32 panel.

import board
import displayio
import framebufferio
import rgbmatrix
import terminalio
from adafruit_display_text.label import Label

# --- Panel geometry ------------------------------------------------------
# One 64x32 HUB75 panel.
DISPLAY_WIDTH = 64
DISPLAY_HEIGHT = 32

# bit_depth trades color depth for RAM/refresh. 4 looks good on a single small
# panel; lower it to 2 if you ever see flicker or run low on memory.
BIT_DEPTH = 4

# --- Colors (0xRRGGBB) ---------------------------------------------------
COLOR_FLIGHT = 0x00CC33   # green  -> a plane is shown
COLOR_INFO = 0xFFAA00     # amber  -> normal status (searching / no flights)
COLOR_ERROR = 0xFF2222    # red    -> something is wrong (Wi-Fi / API)
COLOR_CLOCK = 0x1188FF    # blue   -> clock fallback (no flights nearby)

# terminalio.FONT glyphs are 6 pixels wide; used to center lines.
GLYPH_WIDTH = 6


def build_display():
    """Create and return the FramebufferDisplay for one 64x32 panel.

    IMPORTANT (address pins): a 64x32 panel uses 1/16 scan, which needs FOUR
    address lines: A, B, C, D. This is the key change from Adafruit's example,
    which targets a 64-pixel-tall (1/32 scan) panel and uses FIVE pins (A-E).
    Including MTX_ADDRE here on a 32-tall panel would show a garbled/half image.
    If you ever swap in a panel with a different scan rate, revisit this list.
    """
    displayio.release_displays()  # free the matrix if code restarted

    matrix = rgbmatrix.RGBMatrix(
        width=DISPLAY_WIDTH,
        height=DISPLAY_HEIGHT,
        bit_depth=BIT_DEPTH,
        rgb_pins=[
            board.MTX_B1,
            board.MTX_G1,
            board.MTX_R1,
            board.MTX_B2,
            board.MTX_G2,
            board.MTX_R2,
        ],
        addr_pins=[
            board.MTX_ADDRA,
            board.MTX_ADDRB,
            board.MTX_ADDRC,
            board.MTX_ADDRD,
            # MTX_ADDRE intentionally omitted for a 64x32 (1/16 scan) panel.
        ],
        clock_pin=board.MTX_CLK,
        latch_pin=board.MTX_LAT,
        output_enable_pin=board.MTX_OE,
        tile=1,
        doublebuffer=True,
    )
    # auto_refresh=True keeps the panel lit for us; we never call refresh()
    # manually, so the panel stays on even while the main loop sleeps.
    return framebufferio.FramebufferDisplay(matrix, auto_refresh=True)


class FlightDisplay:
    """Three lines of text on the panel.

    We create the three Label objects ONCE and then only change their `.text`
    and `.color`. This avoids rebuilding a displayio Group on every update
    (which churns memory on a microcontroller).
    """

    def __init__(self, display):
        self.display = display
        self.group = displayio.Group()

        # terminalio.FONT is a built-in 6x8 font. At y = baseline, these three
        # rows sit comfortably within the 32-pixel height.
        self.line1 = Label(terminalio.FONT, text="", color=COLOR_INFO, x=1, y=5)
        self.line2 = Label(terminalio.FONT, text="", color=COLOR_INFO, x=1, y=16)
        self.line3 = Label(terminalio.FONT, text="", color=COLOR_INFO, x=1, y=27)

        self.group.append(self.line1)
        self.group.append(self.line2)
        self.group.append(self.line3)
        self.display.root_group = self.group

    def _center_x(self, text):
        """Left x so `text` sits centered on the 64-wide panel."""
        return max(1, (DISPLAY_WIDTH - len(text) * GLYPH_WIDTH) // 2)

    def _set(self, text1, text2, text3, color, center=False):
        for line, text in (
            (self.line1, text1), (self.line2, text2), (self.line3, text3)
        ):
            line.color = color
            line.text = text
            line.x = self._center_x(text) if center else 1

    def show_flight(self, callsign, altitude, distance):
        """Show the closest aircraft: callsign, altitude, distance."""
        self._set(callsign, altitude, distance, COLOR_FLIGHT)

    def show_status(self, line1, line2="", line3="", is_error=False):
        """Show a status/message screen (no aircraft)."""
        color = COLOR_ERROR if is_error else COLOR_INFO
        self._set(line1, line2, line3, color)

    def show_clock(self, time_text, label="", abbr=""):
        """Clock fallback: centered time with a place label and tz abbrev."""
        self._set(label, time_text, abbr, COLOR_CLOCK, center=True)
