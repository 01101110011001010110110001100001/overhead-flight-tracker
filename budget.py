# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Keeps a rough tally of FlightAware spending so we don't blow the budget.
#
# It remembers two numbers in the board's little scratch memory (NVM): which
# billing month we're in, and how many queries we've made this month. Estimated
# cost is just queries * price-per-query. The count resets each month, and we
# stop allowing queries a bit before the budget so there's a safety margin.
#
# Worth repeating (also in the README): this is only an estimate for THIS board.
# It can't see FlightAware usage from other apps or keys on your account, and it
# assumes the price you set. It's a safety brake, not a hard cap -- your
# AeroAPI dashboard is the real source of truth.
#
# We use NVM instead of a file because the board's filesystem is read-only to the
# code by default, while NVM is always writable and doesn't fight with the USB
# drive.

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
