# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Pure date/time helpers: convert a UTC Unix timestamp into St. Louis (US
# Central) wall-clock time, including daylight saving time.
#
# Why this exists: the board has no reliable real-time clock, but OpenSky stamps
# every API response with a UTC time. We feed that timestamp in here. No
# hardware, no timezone database, no network -> runs and is tested on a desktop.
#
# To adapt for a different US time zone, change STANDARD_OFFSET_HOURS (and the
# abbreviations). US DST rules are the same across the mainland zones.

STANDARD_OFFSET_HOURS = -6   # Central Standard Time (CST) is UTC-6
DAYLIGHT_OFFSET_HOURS = -5   # Central Daylight Time (CDT) is UTC-5
STD_ABBR = "CST"
DST_ABBR = "CDT"

SECONDS_PER_DAY = 86400

# Short names for the date line (index 0 = Sunday, matching _weekday()).
_WEEKDAYS = ("SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT")
_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _civil_from_days(z):
    """Days-since-1970-01-01 -> (year, month, day). Hinnant's algorithm."""
    z += 719468
    era = (z if z >= 0 else z - 146096) // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    if m <= 2:
        y += 1
    return y, m, d


def _days_from_civil(y, m, d):
    """(year, month, day) -> days-since-1970-01-01. Inverse of the above."""
    y -= 1 if m <= 2 else 0
    era = (y if y >= 0 else y - 399) // 400
    yoe = y - era * 400
    mp = m - 3 if m > 2 else m + 9
    doy = (153 * mp + 2) // 5 + d - 1
    doe = yoe * 365 + yoe // 4 - yoe // 100 + doy
    return era * 146097 + doe - 719468


def _weekday(days):
    """days-since-epoch -> weekday, 0=Sunday..6=Saturday (1970-01-01 was Thu)."""
    return (days + 4) % 7


def _nth_sunday(year, month, n):
    """Day-of-month of the n-th Sunday in (year, month)."""
    first = _days_from_civil(year, month, 1)
    offset = (7 - _weekday(first)) % 7   # days from the 1st to the first Sunday
    return 1 + offset + (n - 1) * 7


def _is_us_dst(utc):
    """Is US daylight saving time in effect at this UTC instant?

    DST runs from 2:00 local on the 2nd Sunday of March to 2:00 local on the
    1st Sunday of November. 2:00 CST = 08:00 UTC; 2:00 CDT = 07:00 UTC.
    """
    year, _, _ = _civil_from_days(utc // SECONDS_PER_DAY)
    start = _days_from_civil(year, 3, _nth_sunday(year, 3, 2)) * SECONDS_PER_DAY + 8 * 3600
    end = _days_from_civil(year, 11, _nth_sunday(year, 11, 1)) * SECONDS_PER_DAY + 7 * 3600
    return start <= utc < end


def central_time(utc):
    """UTC Unix seconds -> dict with 24h hour, minute, and tz abbreviation."""
    if _is_us_dst(utc):
        offset = DAYLIGHT_OFFSET_HOURS
        abbr = DST_ABBR
    else:
        offset = STANDARD_OFFSET_HOURS
        abbr = STD_ABBR
    local = int(utc) + offset * 3600
    rem = local % SECONDS_PER_DAY
    return {"hour": rem // 3600, "minute": (rem % 3600) // 60, "abbr": abbr}


def format_central_clock(utc):
    """UTC Unix seconds -> dict with a 12-hour 'time' string and tz 'abbr'.

    Example: {"time": "7:34 PM", "abbr": "CDT"}
    """
    parts = central_time(utc)
    hour24 = parts["hour"]
    ampm = "AM" if hour24 < 12 else "PM"
    hour12 = hour24 % 12
    if hour12 == 0:
        hour12 = 12
    return {
        "time": "{}:{:02d} {}".format(hour12, parts["minute"], ampm),
        "abbr": parts["abbr"],
    }


def utc_from_components(year, month, day, hour, minute, second):
    """Build a UTC Unix timestamp from calendar components (e.g. from NTP)."""
    return (_days_from_civil(year, month, day) * SECONDS_PER_DAY
            + hour * 3600 + minute * 60 + second)


def _local_days(utc):
    """Days-since-epoch for the St. Louis local date at this UTC instant."""
    offset = DAYLIGHT_OFFSET_HOURS if _is_us_dst(utc) else STANDARD_OFFSET_HOURS
    return (int(utc) + offset * 3600) // SECONDS_PER_DAY


def format_central_date(utc):
    """UTC Unix seconds -> short local date string, e.g. 'SAT OCT 4'."""
    days = _local_days(utc)
    year, month, day = _civil_from_days(days)
    return "{} {} {}".format(_WEEKDAYS[_weekday(days)], _MONTHS[month - 1], day)
