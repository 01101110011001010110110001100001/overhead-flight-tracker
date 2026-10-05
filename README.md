# overhead-flight-tracker

A CircuitPython LED display that shows the closest aircraft flying near your
house, using the [OpenSky Network](https://opensky-network.org/) API on an
**Adafruit MatrixPortal S3** driving one **64 × 32 HUB75 LED matrix panel**.

The closest eligible airborne aircraft is shown as three lines:

```
UAL245        <- callsign
10000 ft      <- altitude
3.2 mi        <- horizontal distance from home
```

When nothing qualifies it shows a clear status message, and it distinguishes
"no flights nearby" from stale data, rate limiting, and connection problems.
When the skies are clear it can instead show a **St. Louis digital clock**:

```
ST LOUIS      <- place label
7:34 PM       <- current time (US Central, auto daylight saving)
CDT           <- time-zone abbreviation
```

### What's built so far

- ✅ 64 × 32 panel configured with the **correct 1/16-scan 4-pin** address wiring
- ✅ **Display-only test** with sample data — needs no Wi-Fi or API account
- ✅ **OpenSky** integration (replacing the example's FlightAware) with current
  API fields, units, and limits
- ✅ **OAuth2** client-credentials login with **automatic token renewal** (and
  refresh-on-401)
- ✅ Small **bounding-box** query around your configurable home coordinates
- ✅ Filters out **grounded / position-less / out-of-radius / stale** aircraft
  and shows the **closest** one
- ✅ Correct **unit conversion** (metres→feet, km→miles) with graceful handling
  of missing callsigns/altitudes
- ✅ **~30 s refresh**, rate-limit aware, honours `Retry-After`
- ✅ Distinct screens for **no-flights / stale / Wi-Fi / API / rate-limit**
- ✅ **Wi-Fi & API recovery** with exponential backoff — no restart or request
  storms
- ✅ **St. Louis clock** (with day + date) when no aircraft are nearby, kept
  accurate via **NTP** (a real time server)
- ✅ **Climb/descent arrows** (`^`/`v`) next to altitude
- ✅ Personal **boot splash** (configurable, e.g. `NELA'S SKYWATCH`)
- ✅ **Airline / route / aircraft-type** display via adsbdb enrichment
  (e.g. `Endeavor` / `LEX>ATL` / `CRJ9 8mi`), with graceful fallbacks
- ✅ **Route verification** — a route is shown only when the plane is actually on
  the corridor between those airports; otherwise the line shows altitude, so a
  stale route is never displayed
- ✅ **Neutral white** display, **red only when a plane is nearly overhead**
- ✅ Configurable **brightness** (dim by default — HUB75 panels are glaring)
- ✅ **59 desktop unit tests** pass (filtering, distance, units, color,
  enrichment layout, route verification, clock + DST + NTP conversion)
- ⬜ Flash + run on real hardware (your step — see Setup)

---

## Hardware

- Adafruit MatrixPortal S3
- One 64 × 32 HUB75 RGB LED matrix panel (**1/16 scan** — see note below)
- USB-C power (a solid 5 V / 2 A+ supply; LED panels draw real current)

> **Panel address pins.** A 64 × 32 panel uses **1/16 scan**, which needs **four**
> address lines (A, B, C, D). Adafruit's original example targets a taller
> (1/32 scan) panel and uses five pins (A–E). Using five pins on a 32-tall panel
> produces a garbled/half image. This project uses four — see the comment in
> `flight_display.py`. If your panel is unusual, confirm its scan rate.

---

## Software versions

- **CircuitPython 10.x** for the MatrixPortal S3 (current stable: **10.3.1**,
  download from https://circuitpython.org/board/adafruit_matrixportal_s3/).
  10.x bundles Mozilla CA root certificates, so HTTPS to OpenSky works without
  shipping a `.pem` file. (The code uses the 9.0+ `display.root_group` API.)
- Libraries from the matching **Adafruit CircuitPython Library Bundle** (10.x):
  - `adafruit_display_text`
  - `adafruit_requests` (which also needs `adafruit_connection_manager`)
  - `adafruit_ntp` (accurate clock from a time server)
  - (`board`, `wifi`, `socketpool`, `ssl`, `displayio`, `rgbmatrix`,
    `framebufferio`, `terminalio`, `gc` are built into CircuitPython.)

Desktop tests need only a normal **Python 3** — no extra packages.

---

## Project files

| File | Runs on | What it does |
|---|---|---|
| `code.py` | board | Main app: settings, Wi-Fi, refresh loop, recovery |
| `flight_display.py` | board | 64 × 32 panel setup + rendering |
| `opensky.py` | board (network) | OAuth2 login, token renewal, `/states/all` |
| `enrich.py` | board (network) | Airline/route/type lookup via adsbdb, cached |
| `flight_filter.py` | anywhere | Distance, filtering, unit + layout formatting (pure) |
| `clock.py` | anywhere | UTC → St. Louis (US Central) time with DST (pure logic) |
| `display_test.py` | board | Display-only demo, **no credentials needed** |
| `tests/test_flight_filter.py` | desktop | Unit tests for the filtering logic |
| `tests/test_clock.py` | desktop | Unit tests for the clock (incl. DST) |
| `settings.toml.example` | — | Documented config template |
| `settings.toml` | board | **Your private** config (git-ignored) |

---

## Setup

### 1. Get an OpenSky API client (free)

Create an account at https://opensky-network.org/, then open your **Account**
page → **API Client** and create a client. Copy the **client_id** and
**client_secret** — these are your OAuth2 credentials.

### 2. Create your private settings

```sh
cp settings.toml.example settings.toml
```

Edit `settings.toml` and fill in Wi-Fi, OpenSky client id/secret, and your home
coordinates. Every setting is explained inline in the file.

> **Decimals must be quoted.** CircuitPython's `settings.toml` only supports
> strings and integers, so latitude/longitude/radius are written as quoted
> strings (e.g. `HOME_LAT = "40.7128"`); the code calls `float()` on them.

`settings.toml` is listed in `.gitignore` and must never be committed. The code
never prints your secrets.

### 3. Run the desktop tests (optional but recommended)

No board required:

```sh
python -m unittest discover -s tests
```

### 4. Try the display-only test on the board (no credentials)

This proves wiring + rendering before any networking. Copy these files onto the
`CIRCUITPY` drive, with **`display_test.py` copied/renamed to `code.py`**:

```
CIRCUITPY/
├── code.py            <- a COPY of display_test.py
├── flight_display.py
├── flight_filter.py
├── clock.py
└── lib/
    └── adafruit_display_text/   (the only library the display test needs)
```

You should see sample flights and every status screen cycle on the panel.

### 5. Run the real tracker

Copy the full project to `CIRCUITPY` so the drive looks like this:

```
CIRCUITPY/
├── code.py              <- the real app (this repo's code.py)
├── flight_display.py
├── flight_filter.py
├── opensky.py
├── enrich.py
├── clock.py
├── settings.toml        <- your private config
└── lib/
    ├── adafruit_display_text/
    ├── adafruit_requests.mpy
    ├── adafruit_connection_manager.mpy
    └── adafruit_ntp.mpy
```

> Do **not** put `display_test.py`, `tests/`, `settings.toml.example`, or
> `README.md` on the board — they aren't used there. Only the files shown above.

The board auto-runs `code.py`. Open the serial console to watch the log.

---

## How it works (plain language)

1. **Settings** load from `settings.toml` (decimals come in as quoted strings).
2. A small **bounding box** is computed around your home, sized to your search
   radius — kept tiny so each API call costs just **1 credit**.
3. Every ~`REFRESH_SECONDS` the app asks OpenSky `/states/all` for aircraft in
   that box (OAuth2 Bearer token; renewed automatically before expiry and again
   if the API returns 401).
4. `flight_filter.select_closest` drops anything **on the ground**, **without a
   valid position**, **outside the radius** (exact great-circle distance), or
   with a **stale** position (older than `STALE_SECONDS`, judged against
   OpenSky's own response timestamp so the board needs no accurate clock).
5. The **closest** survivor is looked up on **adsbdb** (airline + route by
   callsign, aircraft type by hex; cached) and shown as **airline / route /
   type+distance** in neutral **white**, turning **red** only when the plane is
   within `CLOSE_RADIUS` (nearly overhead).
6. **The route is verified before it's shown.** adsbdb routes are keyed by flight
   number and are often stale, so a route is displayed only when the plane is
   actually on the corridor between those two airports (origin→plane→destination
   ≈ origin→destination). If it isn't — or there's no route (e.g. a private
   plane) — the middle line shows the **altitude** instead. (See "Routes and the
   certificate limitation" below for why we don't use the OpenSky map's source.)
7. If nothing qualifies and `CLOCK_FALLBACK` is on, the panel shows a **St.
   Louis clock** (see below); otherwise `NO FLIGHTS`. If nearby planes were only
   dropped for staleness, you get `STALE DATA`; network/API problems show
   `NO SIGNAL` / `WIFI ERROR` / `API ERROR` / `RATE LIMIT`.
8. Failures trigger **exponential backoff** (5 s → 300 s) so the board never
   restart-storms or hammers the API; a success resets the backoff. Rate-limit
   responses wait the server's `Retry-After`.

### Clock fallback

When no aircraft are nearby, the display shows the current **St. Louis (US
Central)** time instead of a blank "no flights" message. The time is fetched from
an **NTP time server** (`adafruit_ntp`, re-synced hourly) and extrapolated with
the board's monotonic timer between syncs, so it's accurate to the second — **no
battery-backed real-time clock needed**. If NTP is blocked on your network, it
falls back to OpenSky's response timestamp (a few seconds less accurate).
`clock.py` applies US daylight saving automatically (CST ↔ CDT) and shows the
weekday + date. Turn it off with `CLOCK_FALLBACK = "false"`, or relabel it with
`CLOCK_LABEL`.

### Routes and the certificate limitation

Routes come from **adsbdb**, whose server uses a Let's Encrypt certificate the
board trusts. The data the OpenSky map itself uses (adsb.lol's VRS standing data)
is more complete and leg-aware, but that host serves a **Google Trust Services**
certificate, and CircuitPython's trimmed on-board CA bundle doesn't include that
root — so the MatrixPortal can't verify it (and CircuitPython can't disable
verification or add a second root). The practical effect: we show adsbdb's route
**only when the plane is verifiably on that corridor**, and altitude otherwise.
You'll see fewer routes than the website, but never a wrong one.

### Personal touches

- **Neutral colors** — the display is plain **white**, turning **red** only when
  a plane is within `CLOSE_RADIUS` (nearly overhead). Errors use a muted amber.
- **Climb/descent** — a trailing `^` (climbing) or `v` (descending) next to the
  altitude, from the aircraft's vertical rate. (ASCII, so it renders on any
  built-in font.)
- **Boot splash** — a quick centered splash on startup, set via `SPLASH_TOP` /
  `SPLASH_BOTTOM` (defaults to `NELA'S` / `SKYWATCH`).

### API usage / rate limits

A free **authenticated** OpenSky account gets **~4,000 credits/day** for the
states endpoint; a small bbox costs **1 credit** per request. At the default 30 s
refresh that's ~2,880 requests/day — within budget. Going much faster than 30 s
risks exhausting the daily quota; `REFRESH_SECONDS` is configurable.

---

## Desktop checks vs. board tests

- **Desktop (your Mac), no hardware:** `tests/` covers all the pure logic —
  distance, filtering, unit conversion, stale detection (`test_flight_filter.py`)
  and the Central-time clock incl. daylight-saving transitions, cross-checked
  against Python's IANA timezone database (`test_clock.py`). The OpenSky client's
  token/401/429 logic is also exercisable with a mock session. **24 tests, all
  passing.**
- **Board only:** anything importing `board` / `rgbmatrix` — i.e.
  `flight_display.py`, `display_test.py`, and `code.py`. These can only truly be
  verified on the MatrixPortal S3 with the panel attached.

Hardware has **not** been tested yet — verify on your board.

---

## Credits & licensing

- The RGBMatrix pin setup is adapted from Adafruit's
  **MatrixPortal S3 Flight Proximity Tracker** example:
  *SPDX-FileCopyrightText: 2023 Trevor Beaton for Adafruit Industries;
  SPDX-License-Identifier: MIT.*
  https://learn.adafruit.com/matrixportal-s3-flight-proximity-tracker
  (The original uses FlightAware and a 128 × 64 display; this project replaces
  FlightAware with OpenSky and targets a 64 × 32 panel.)
- Live aircraft positions: **The OpenSky Network**, https://opensky-network.org/.
- Routes, airline names, and aircraft types: **adsbdb**, https://www.adsbdb.com/
  (free, no key). Per adsbdb's terms, route data is the work of **David Taylor
  (Edinburgh)** and **Jim Mason (Glasgow)**; aircraft data is from **PlaneBase**.
  (adsb.lol's VRS standing data would match the OpenSky map more closely, but its
  host's certificate isn't verifiable on the board — see "Routes and the
  certificate limitation".)
- Time: public **NTP** pool via `adafruit_ntp`.
- This project is released under the **MIT License** (see `LICENSE`,
  Copyright 2026 Nela) — your chosen license for your original contributions.
  Adafruit's adapted portions remain under their original MIT notice, preserved
  in `flight_display.py`. Both are MIT, so the whole project is consistently MIT.

---

## Progress checklist

- [x] Inspect existing repo files
- [x] Obtain Adafruit example code + preserve its copyright/license
- [x] Confirm 64 × 32 panel address-pin/scan requirement (4 pins, 1/16 scan)
- [x] Configure display for one 64 × 32 panel
- [x] Display-only test with sample data (`display_test.py`), no credentials
- [x] Replace FlightAware with OpenSky (current API fields/units/limits)
- [x] OAuth2 client-credentials auth + automatic token renewal
- [x] Query a small bounding box around configurable home coordinates
- [x] Exclude on-ground / missing-position / stale aircraft
- [x] Horizontal distance + radius filter + pick closest
- [x] Readable callsign / altitude / distance layout with unit conversion
- [x] ~30 s refresh, rate-limit aware, honors Retry-After
- [x] Distinct messages for no-flights vs. stale vs. connection failures
- [x] Wi-Fi/API recovery with exponential backoff (no restart/request storms)
- [x] Reviewed the starter's loop/empty-handling/cleanup/display bugs
- [x] St. Louis (US Central) clock with daylight saving + date, accurate via NTP
- [x] Personal zest: proximity color, climb/descent arrows, boot splash
- [x] Secrets in git-ignored `settings.toml`; documented `settings.toml.example`
- [x] MIT license confirmed for original contributions
- [x] Desktop unit tests pass — 59/59 (`python -m unittest discover -s tests`)
- [ ] **Flash CircuitPython 9.x + libraries onto the board** (you)
- [ ] **Run the display test on real hardware** (you)
- [ ] **Run the full tracker with real credentials** (you)
