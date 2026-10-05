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

from flight_filter import scale_color, COLOR_NORMAL

# --- Panel geometry ------------------------------------------------------
# One 64x32 HUB75 panel.
DISPLAY_WIDTH = 64
DISPLAY_HEIGHT = 32

# bit_depth trades color depth for RAM/refresh. 4 looks good on a single small
# panel; lower it to 2 if you ever see flicker or run low on memory.
BIT_DEPTH = 4

# --- Colors (0xRRGGBB) ---------------------------------------------------
# Neutral palette: almost everything is plain white. Red is reserved for a
# super-close plane (set per-flight via the color passed to show_flight).
# The one other accent is a muted amber for genuine errors, so a problem still
# stands out. Everything is further dimmed by `brightness`.
COLOR_FLIGHT = COLOR_NORMAL  # white -> a plane is shown (red when super close)
COLOR_INFO = COLOR_NORMAL    # white -> normal status (searching / no flights)
COLOR_CLOCK = COLOR_NORMAL   # white -> clock fallback
COLOR_ERROR = 0xFFAA00       # amber -> something is wrong (Wi-Fi / API)

# terminalio.FONT glyphs are 6 pixels wide; used to center lines.
GLYPH_WIDTH = 6

# Default panel brightness (0.0 = off .. 1.0 = full/neon). HUB75 panels are
# very bright at full, so we dim by default. Override per-FlightDisplay or via
# the BRIGHTNESS setting in settings.toml.
DEFAULT_BRIGHTNESS = 0.3


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
    """Three horizontally-centered lines of the built-in 6x8 font.

    Labels are created once and only their text/color change (no per-update Group
    rebuild). Used for flights (callsign/route / altitude/type / distance), the
    clock, status messages, and the boot splash.
    """

    def __init__(self, display, brightness=DEFAULT_BRIGHTNESS):
        self.display = display
        self.brightness = brightness
        self.group = displayio.Group()
        # Three rows, centered horizontally, spaced within the 32-pixel height.
        self.line1 = self._centered_label(DISPLAY_WIDTH // 2, 6)
        self.line2 = self._centered_label(DISPLAY_WIDTH // 2, 16)
        self.line3 = self._centered_label(DISPLAY_WIDTH // 2, 26)
        for line in (self.line1, self.line2, self.line3):
            self.group.append(line)
        self.display.root_group = self.group

    def _centered_label(self, cx, cy):
        label = Label(terminalio.FONT, text="", color=COLOR_NORMAL)
        label.anchor_point = (0.5, 0.5)       # center the text on (cx, cy)
        label.anchored_position = (cx, cy)
        return label

    def _set(self, text1, text2, text3, color):
        dimmed = scale_color(color, self.brightness)
        for line, text in (
            (self.line1, text1), (self.line2, text2), (self.line3, text3)
        ):
            line.color = dimmed
            line.text = text

    def show_flight(self, callsign, altitude, distance, color=None):
        """Flight view: three centered lines (route/callsign, type/alt, distance)."""
        self._set(callsign, altitude, distance,
                  COLOR_FLIGHT if color is None else color)

    def show_status(self, line1, line2="", line3="", is_error=False):
        """Centered status/message screen (no aircraft)."""
        self._set(line1, line2, line3, COLOR_ERROR if is_error else COLOR_INFO)

    def show_clock(self, time_text, label="", date_text=""):
        """Centered place label, time, and date."""
        self._set(label, time_text, date_text, COLOR_CLOCK)

    def show_splash(self, line1, line2=""):
        """Centered boot splash (e.g. a personal name)."""
        self._set(line1, line2, "", COLOR_FLIGHT)
