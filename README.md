# overhead-flight-tracker

A CircuitPython LED display that shows the closest aircraft flying near your
house on an **Adafruit MatrixPortal S3** driving one **64 × 32 HUB75 LED panel**.

It combines two data sources:

- **OpenSky Network** — detects nearby aircraft and provides their live
  **positions**, which the code turns into **distance from your house**.
- **FlightAware AeroAPI** — fills in the **departure airport → destination
  airport** and **aircraft type** for each newly detected flight.

The closest eligible airborne aircraft is shown as three horizontally-centered
lines:

```
DFW>STL      <- departure airport > destination airport (from FlightAware)
A319         <- aircraft type (from FlightAware)
8.0 mi       <- distance from home (from OpenSky's latest position)
```

- When FlightAware has no data for a flight (no key, budget used up, unknown
  flight, or an API error), the middle lines fall back to the **callsign** and
  **altitude** — OpenSky tracking always keeps working.
- The text is **white**, turning **red** only when a plane is within
  `CLOSE_RADIUS` (nearly overhead).
- When no aircraft are nearby, the panel shows a **St. Louis clock** (24-hour,
  with the date), kept accurate by an NTP time server.

---

## How it works (plain language)

1. Every ~`REFRESH_SECONDS`, the app asks **OpenSky** for aircraft inside a small
   box around your home (OAuth2; token auto-renews).
2. It drops anything on the ground, without a valid position, outside your
   radius (exact great-circle distance), or with a stale position, and keeps the
   **closest** one. Distance is computed from OpenSky's latest coordinates.
3. For that aircraft, it asks **FlightAware** `GET /flights/{ident}?max_pages=1`
   (ident = the OpenSky callsign) and picks the **currently airborne** flight —
   the one that has actually departed (`actual_off`) but not yet arrived
   (`actual_on`) — so it won't grab an old or future flight with the same number.
4. The route + type are **cached per aircraft** (by its ICAO24 hex id). Position
   updates and screen redraws reuse the cache and **never** trigger another
   FlightAware request. A given plane is looked up at most once.
5. If FlightAware is disabled, out of budget, rate-limited, or doesn't know the
   flight, the plane still shows via OpenSky (callsign + altitude + distance).

---

## Hardware

- Adafruit MatrixPortal S3
- One 64 × 32 HUB75 RGB LED matrix panel (**1/16 scan** — uses 4 address pins
  A–D, not 5; see the comment in `flight_display.py`)
- USB-C power (a solid 5 V / 2 A+ supply)

---

## Software versions

- **CircuitPython 10.x** for the MatrixPortal S3 (current stable: **10.3.1**,
  from https://circuitpython.org/board/adafruit_matrixportal_s3/).
- Libraries from the matching **Adafruit CircuitPython Library Bundle** (10.x):
  - `adafruit_display_text`
  - `adafruit_requests` (also needs `adafruit_connection_manager`)
  - `adafruit_ntp`
  - (`board`, `wifi`, `socketpool`, `ssl`, `displayio`, `rgbmatrix`,
    `framebufferio`, `terminalio`, `microcontroller`, `gc` are built in.)

Desktop tests need only ordinary **Python 3** — no extra packages.

---

## Project files

| File | Runs on | What it does |
|---|---|---|
| `code.py` | board | Main app: settings, Wi-Fi, loop, recovery |
| `flight_display.py` | board | 64 × 32 panel setup + rendering |
| `opensky.py` | board (network) | OpenSky OAuth2 + positions |
| `flightaware.py` | board (network) | FlightAware route/type lookups (cached) |
| `budget.py` | board | FlightAware spend tracker, persisted in NVM |
| `flight_filter.py` | anywhere | Distance, filtering, display formatting (pure) |
| `clock.py` | anywhere | UTC → St. Louis time + date (pure) |
| `flightaware_ssl_root.pem` | board | Root cert for FlightAware's API host |
| `display_test.py` | board | Display-only demo, **no credentials needed** |
| `tests/` | desktop | Unit tests (no board, no network) |
| `settings.toml.example` | — | Documented config template |
| `settings.toml` | board | **Your private** config (git-ignored) |

---

## Setup

### 1. Accounts & keys

- **OpenSky** (required): create a free account at https://opensky-network.org/,
  then **Account → API Client** to get a `client_id` and `client_secret`.
- **FlightAware AeroAPI** (optional but needed for route/type): sign up at
  https://flightaware.com/aeroapi/ and create a key. The **Personal** tier
  includes **$5 of free usage per month**.

### 2. Private settings

```sh
cp settings.toml.example settings.toml
```

Fill in `settings.toml` (every line is explained in the file). It holds your
Wi-Fi, OpenSky credentials, FlightAware key, home coordinates, and budget.

> **Decimals must be quoted.** CircuitPython's `settings.toml` parser only
> supports strings and integers, so latitude, longitude, radius, brightness, and
> the dollar amounts are written as quoted strings (e.g. `HOME_LAT = "38.49"`);
> the code calls `float()` on them.

`settings.toml` is listed in `.gitignore` and is never committed. The example
file contains only placeholders — no real keys, passwords, or coordinates. The
code never prints your key or secrets.

### 3. Desktop tests (optional, no hardware)

```sh
python -m unittest discover -s tests
```

### 4. Try the display test first (no credentials)

Copy the display-test files onto `CIRCUITPY`, with **`display_test.py` copied to
`code.py`**:

```
CIRCUITPY/
├── code.py            <- a COPY of display_test.py
├── flight_display.py
├── flight_filter.py
├── clock.py
└── lib/
    └── adafruit_display_text/
```

You'll see sample flights (route / type / distance), the clock, and status
screens cycle — all offline.

### 5. Deploy the real tracker

Copy the full project to `CIRCUITPY`:

```
CIRCUITPY/
├── code.py
├── flight_display.py
├── flight_filter.py
├── opensky.py
├── flightaware.py
├── budget.py
├── clock.py
├── flightaware_ssl_root.pem   <- required for FlightAware HTTPS
├── settings.toml              <- your private config
└── lib/
    ├── adafruit_display_text/
    ├── adafruit_requests.mpy
    ├── adafruit_connection_manager.mpy
    └── adafruit_ntp.mpy
```

The board auto-runs `code.py`. Watch the serial console to see what it's doing
(it prints the closest flight and, when idle, the clock — never your secrets).

> **Why the `.pem`?** FlightAware's API host uses an **SSL.com** certificate that
> isn't in CircuitPython's built-in trust list, so the code loads this root for a
> dedicated FlightAware connection. OpenSky (Let's Encrypt) uses the built-in
> list. Without the `.pem`, FlightAware is skipped and the tracker runs
> OpenSky-only.

---

## Cost & budget

**Verify prices yourself before relying on these numbers** — the authoritative,
per-query price is shown in **your AeroAPI dashboard**.

What is confirmed from FlightAware's public materials (as of October 2026):

- **Personal tier: $5 of free usage per month**, usage-based, **billed monthly**.
- Pricing is **per "result set"**, where a result set = **15 results**.
- `GET /flights/{ident}` with `max_pages=1` returns at most 15 results, so it
  counts as **one result set (one billable unit) per query**.
- The exact dollar amount for this endpoint's class is only shown in the
  logged-in portal, so the code treats the **per-query price as a setting**
  (`FLIGHTAWARE_COST_PER_QUERY`, default a conservative **$0.012**). Set it to the
  figure your dashboard shows.

**Your budget:** `$15 total = $5 free credit + up to $10 you're willing to pay`.
Set `FLIGHTAWARE_BUDGET_USD = "15"`. The code keeps a margin
(`FLIGHTAWARE_MARGIN_USD`, default `$0.50`) and **stops making FlightAware
requests before the budget is reached** (so at the default price it allows about
`$14.50 / $0.012 ≈ 1,200` lookups per month). When the budget is exhausted,
**OpenSky tracking continues** — you just see callsign + altitude instead of
route + type until the next billing month.

**How spend is tracked:** each billable (HTTP 200) FlightAware query increments a
counter stored in the board's **non-volatile memory (NVM)**, so the estimate
**persists across restarts, retries, and testing**. The counter resets when the
billing month rolls over (detected from the NTP clock).

**Seeing your spend:** once an hour (and at startup) the board logs a line to the
serial console like:

```
FlightAware budget: est. $0.06 of $14.50 spent this month (5 queries)
```

(It's a log line, not a push notification — the board can't message your phone on
its own.)

### ⚠️ Limits of this local spending protection

This is a **local estimate for this one device** — a safety brake, **not a
guaranteed account-wide spending cap**:

- It can't see FlightAware requests made by **other programs, other computers, or
  other API keys** on the same FlightAware account.
- It assumes each query bills as exactly **one result set** and uses the
  **price you configured**, which may differ from FlightAware's actual billing.
- If NVM is unavailable or reset, the counter can under-count.

Treat your **AeroAPI dashboard** as the source of truth, and consider setting a
spending limit there too if the provider offers one.

---

## Caching & missing data

- **One lookup per aircraft.** Results (including "no route found") are cached by
  the aircraft's hex id, so screen changes and OpenSky position updates never
  cost extra FlightAware queries.
- **Missing callsign** → no FlightAware lookup; shows `UNKNOWN` + altitude.
- **Unknown flight / no route** → shows callsign + altitude (cached so it isn't
  retried).
- **API failures:** a `401` disables FlightAware for the session (check your
  key); a `429` (rate limit) starts a cooldown; other errors are logged and the
  flight still shows via OpenSky.

## Clock

When no aircraft are nearby, the panel shows the **St. Louis (US Central)** time
(24-hour) and date. The time comes from an **NTP server** (`adafruit_ntp`,
re-synced about hourly and advanced by the board's timer in between), so it's
accurate to the second with no battery-backed clock. US daylight saving is
applied automatically (CST ↔ CDT). Turn the clock off with
`CLOCK_FALLBACK = "false"` or relabel it with `CLOCK_LABEL`.

---

## Desktop checks vs. board tests

- **Desktop (no hardware):** `tests/` covers the pure logic — distance,
  filtering, unit/line formatting, colors, the clock (incl. DST, cross-checked
  against Python's timezone database), the budget tracker (via a bytearray
  standing in for NVM), and the FlightAware parsing/caching/budget logic (via a
  mock session). Run `python -m unittest discover -s tests`.
- **Board only:** anything importing `board` / `rgbmatrix` / `microcontroller` —
  `flight_display.py`, `display_test.py`, `code.py`. Verify these on the
  MatrixPortal S3 with the panel attached.

---

## Credits & licensing

- RGBMatrix pin setup adapted from Adafruit's **MatrixPortal S3 Flight Proximity
  Tracker** example: *SPDX-FileCopyrightText: 2023 Trevor Beaton for Adafruit
  Industries; MIT.* https://learn.adafruit.com/matrixportal-s3-flight-proximity-tracker
  (The original uses FlightAware with a 128 × 64 display; this project adds
  OpenSky for positions and targets a 64 × 32 panel.)
- Aircraft positions: **The OpenSky Network**, https://opensky-network.org/.
- Route & aircraft type: **FlightAware AeroAPI**, https://flightaware.com/aeroapi/.
- Time: public **NTP** pool via `adafruit_ntp`.
- Released under the **MIT License** (see `LICENSE`, Copyright 2026 Nela).
  Adafruit's adapted portions keep their original MIT notice in
  `flight_display.py`.
