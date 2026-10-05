# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Estimated FlightAware spend tracker, persisted across restarts.
#
# It stores two things in the board's non-volatile memory (microcontroller.nvm):
#   * the current billing month id, and
#   * how many billable FlightAware queries we've made this month.
# Estimated cost = query_count * cost_per_query. When the month rolls over, the
# count resets. We stop allowing queries a little before the budget, leaving a
# margin.
#
# IMPORTANT (and documented in the README): this is a LOCAL estimate for THIS
# device only. It cannot see FlightAware requests made by other programs, other
# machines, or other API keys on the same account, and it assumes each query
# bills as exactly one result set. Treat it as a safety brake, NOT a guaranteed
# account-wide spending cap. The real, authoritative usage is in your FlightAware
# AeroAPI dashboard.
#
# NVM is used (not a file) because CircuitPython's filesystem is read-only to
# code unless a boot.py remounts it, whereas nvm is always writable by code and
# doesn't conflict with the USB drive.

import struct

try:
    import microcontroller
    _DEFAULT_NVM = microcontroller.nvm
except ImportError:  # desktop / tests
    _DEFAULT_NVM = None

_MAGIC = 0xB2
_VERSION = 1
_FMT = "<BBHI"                   # magic, version, month_id, count
_SIZE = struct.calcsize(_FMT)    # 8 bytes


class BudgetTracker:
    def __init__(self, cost_per_query, budget_usd, margin_usd=0.5, nvm=None):
        self.cost_per_query = float(cost_per_query)
        # Stop before the allowance, keeping a margin.
        self.hard_limit = max(0.0, float(budget_usd) - float(margin_usd))
        self._nvm = nvm if nvm is not None else _DEFAULT_NVM
        self.month_id = 0
        self.count = 0
        self._load()

    def _load(self):
        if self._nvm is None:
            return
        try:
            magic, version, month_id, count = struct.unpack(
                _FMT, bytes(self._nvm[0:_SIZE]))
            if magic == _MAGIC and version == _VERSION:
                self.month_id = month_id
                self.count = count
        except (ValueError, OSError):
            pass  # uninitialized/corrupt NVM -> start fresh

    def _save(self):
        if self._nvm is None:
            return
        try:
            self._nvm[0:_SIZE] = struct.pack(
                _FMT, _MAGIC, _VERSION, self.month_id & 0xFFFF, self.count & 0xFFFFFFFF)
        except (ValueError, OSError):
            pass

    def set_month(self, month_id):
        """Tell the tracker the current billing month; resets on rollover."""
        if month_id and month_id != self.month_id:
            self.month_id = month_id
            self.count = 0
            self._save()

    def spent_usd(self):
        return self.count * self.cost_per_query

    def remaining_usd(self):
        return max(0.0, self.hard_limit - self.spent_usd())

    def can_query(self):
        """True if one more query stays within the margin-reduced budget."""
        return (self.spent_usd() + self.cost_per_query) <= self.hard_limit

    def record_query(self):
        """Count one billable query and persist immediately."""
        self.count += 1
        self._save()
