# overhead-flight-tracker

A little LED sign that shows the plane flying closest to your house. It runs on
an Adafruit MatrixPortal S3 with one 64x32 LED panel.

Two services do the work:

- **OpenSky** tells us where planes are (their live positions), which we turn
  into a distance from your house.
- **FlightAware** fills in the fun details for the closest plane: where it's
  coming from, where it's going, and what kind of aircraft it is.

The closest plane shows up as three centered lines:

```
DFW>STL      from airport > to airport   (FlightAware)
A319         aircraft type               (FlightAware)
8.0 mi       distance from your house     (OpenSky)
```

A few nice touches:

- The aircraft type is shown as a friendly model name where we know it
  (`BCS1` becomes `A220-100`, `B738` becomes `737-800`, and so on). Anything not
  in the list just shows its short code. The list lives in `flight_filter.py`
  (`AIRCRAFT_NAMES`) if you want to add more.
- If FlightAware doesn't know a flight (or you've hit your budget), it just
  shows the callsign and altitude instead. OpenSky tracking never stops.
- Text is white, and turns red only when a plane is nearly overhead.
- When the skies are quiet, the panel shows a St. Louis clock with the date.

---

## How it works

Every 30 seconds or so:

1. Ask OpenSky what's flying in a small box around your house.
2. Ignore anything on the ground, too far away, or with no/old position, and
   keep the closest plane. Its distance comes from OpenSky's latest position.
3. Ask FlightAware about that plane (by its callsign) and pick the flight that's
   actually in the air right now, so we don't grab yesterday's or tomorrow's
   flight with the same number.
4. Remember that plane's route and type, so we only ever ask FlightAware about
   it once — redraws and position updates are free.
5. If FlightAware can't help (no key, out of budget, unknown flight, hiccup),
   just show the callsign + altitude. The plane still shows up.

---

## What you need

Hardware:

- Adafruit MatrixPortal S3
- One 64x32 HUB75 LED panel (the common "1/16 scan" kind, which uses 4 address
  pins — the code is set up for that)
- A USB-C power supply that can push a couple of amps

Software:

- CircuitPython 10.x for the MatrixPortal S3
  (https://circuitpython.org/board/adafruit_matrixportal_s3/)
- A few libraries from the matching Adafruit library bundle:
  `adafruit_display_text`, `adafruit_requests` (which also needs
  `adafruit_connection_manager`), and `adafruit_ntp`.

The desktop tests just need plain Python 3.

---

## The files

| File | What it does |
|---|---|
| `code.py` | The main program: settings, Wi-Fi, the loop |
| `flight_display.py` | Sets up the panel and draws the text |
| `opensky.py` | Talks to OpenSky (positions) |
| `flightaware.py` | Talks to FlightAware (route + type) |
| `budget.py` | Keeps a running estimate of FlightAware spend |
| `flight_filter.py` | Picks the closest plane and formats the lines |
| `clock.py` | Turns UTC into St. Louis time |
| `flightaware_ssl_root.pem` | A certificate FlightAware needs (see note below) |
| `display_test.py` | A no-internet demo you can run to check the screen |
| `tests/` | Tests you can run on your computer |
| `settings.toml.example` | A template for your settings |
| `settings.toml` | Your private settings (never committed) |

---

## Setup

### 1. Get your accounts

- OpenSky (needed): make a free account at https://opensky-network.org/, then
  go to Account -> API Client to get a client id and secret.
- FlightAware (optional, but it's what gives you the route and type): sign up at
  https://flightaware.com/aeroapi/ and make a key. The Personal plan comes with
  $5 of free usage a month.

### 2. Fill in your settings

Copy the template and edit it:

```sh
cp settings.toml.example settings.toml
```

Every line is explained inside the file. One thing to know: CircuitPython's
settings file only understands text and whole numbers, so anything with a
decimal point (your coordinates, radius, dollar amounts) needs to be in quotes,
like `HOME_LAT = "38.49"`. The code turns those back into numbers.

`settings.toml` is git-ignored, so your Wi-Fi password and keys stay on your
machine. The example file only has fake placeholders.

### 3. (Optional) run the tests on your computer

```sh
python -m unittest discover -s tests
```

### 4. Check the screen first (no accounts needed)

Copy these onto the CIRCUITPY drive, using `display_test.py` as `code.py`:

```
CIRCUITPY/
├── code.py            (a copy of display_test.py)
├── flight_display.py
├── flight_filter.py
├── clock.py
└── lib/
    └── adafruit_display_text/
```

It'll cycle through some sample flights, the clock, and the status screens — all
offline, so you can confirm the panel looks right before dealing with Wi-Fi.

### 5. Run the real thing

Copy the whole project onto CIRCUITPY:

```
CIRCUITPY/
├── code.py
├── flight_display.py
├── flight_filter.py
├── opensky.py
├── flightaware.py
├── budget.py
├── clock.py
├── flightaware_ssl_root.pem
├── settings.toml
└── lib/
    ├── adafruit_display_text/
    ├── adafruit_requests.mpy
    ├── adafruit_connection_manager.mpy
    └── adafruit_ntp.mpy
```

The board runs `code.py` on its own. Plug it into a computer and open the serial
console if you want to watch what it's doing (it prints the current plane or
clock — never your secrets).

Note on that `.pem` file: FlightAware's server uses a certificate the board
doesn't recognize out of the box, so we ship the certificate it needs. If you
leave it out, FlightAware is just skipped and you get OpenSky-only.

---

## Money stuff

Short version: you set a monthly budget, the code stops calling FlightAware
before it hits that budget, and OpenSky keeps running either way.

A few things worth knowing (and worth double-checking on your own AeroAPI
dashboard, since prices can change):

- The Personal plan gives you $5 of free usage per month.
- You're billed per "result set" (a batch of up to 15 results). Our query asks
  for one plane at a time, so it's one result set per lookup.
- FlightAware only shows the exact per-query price once you're logged in, so the
  code treats that price as a setting (`FLIGHTAWARE_COST_PER_QUERY`). The default
  is a deliberately high guess so you under-spend rather than over-spend. Set it
  to whatever your dashboard shows.

The budget itself is `FLIGHTAWARE_BUDGET_USD` (default $15 = the $5 free credit
plus $10 you're okay paying). The code leaves a small margin and stops before
reaching it. When it stops, you just see callsign + altitude until next month.

Spending is tracked in the board's memory so it survives restarts and resets
each month. Once an hour the board prints a line like:

```
FlightAware budget: est. $0.06 of $14.50 spent this month (5 queries)
```

One honest caveat: this is just a local estimate for this one board. It can't
see FlightAware usage from other apps or keys on your account, and it assumes
the price you set. Think of it as a safety brake, not a hard cap — your
AeroAPI dashboard is the real source of truth.

---

## When FlightAware can't help

- Each plane is looked up once, then remembered — redraws and position updates
  don't cost anything.
- No callsign? We skip the lookup and show the altitude.
- Unknown flight? Show callsign + altitude (and remember it, so we don't keep
  asking).
- A bad key stops FlightAware for the session; a rate-limit triggers a short
  cooldown. Either way, the plane still shows via OpenSky.

## The clock

When nothing's nearby, you get a 24-hour St. Louis clock with the date. It gets
the real time from an internet time server (NTP) about once an hour and counts
seconds on its own in between, so it stays accurate without a battery clock.
Daylight saving is handled for you. You can turn it off with
`CLOCK_FALLBACK = "false"` or rename it with `CLOCK_LABEL`.

## Nightly sleep

No point lighting up the room (or spending API calls) while you're asleep. Set
the quiet hours in your settings and the board turns the screen off and pauses
both APIs during that window, then wakes up on its own:

```
SLEEP_START_HOUR = 0    # midnight
SLEEP_END_HOUR   = 8    # 8 AM
```

Hours are 0-23 in local time, and the window can cross midnight (e.g. 22 to 6).
To turn sleep off entirely, set both to the same number. While asleep the board
isn't drawing anything or calling OpenSky/FlightAware, so it also saves your
daily OpenSky quota and FlightAware budget.

---

## Testing

- On your computer (no board): `python -m unittest discover -s tests` checks the
  logic that doesn't need hardware — distance, filtering, formatting, colors, the
  clock (including daylight saving), the budget tracker, and the FlightAware
  parsing/caching.
- On the board: the display, Wi-Fi, and API parts can only really be checked on
  the MatrixPortal itself.

---

## Credits & license

- The panel pin setup is adapted from Adafruit's MatrixPortal S3 Flight Proximity
  Tracker example (2023 Trevor Beaton for Adafruit Industries, MIT):
  https://learn.adafruit.com/matrixportal-s3-flight-proximity-tracker . That one
  used FlightAware with a bigger display; this project adds OpenSky and targets a
  64x32 panel.
- Plane positions: The OpenSky Network, https://opensky-network.org/
- Route and aircraft type: FlightAware AeroAPI, https://flightaware.com/aeroapi/
- Time: public NTP servers via `adafruit_ntp`
- MIT License (see `LICENSE`, Copyright 2026 Nela). Adafruit's adapted bits keep
  their original MIT notice in `flight_display.py`.
