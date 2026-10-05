# SPDX-FileCopyrightText: 2026 Nela
# SPDX-License-Identifier: MIT
#
# Desktop tests for budget.py. Uses a bytearray in place of microcontroller.nvm.
#   python -m unittest discover -s tests

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import budget


class BudgetTrackerTests(unittest.TestCase):
    def _nvm(self):
        return bytearray(16)  # stand-in for microcontroller.nvm

    def test_cost_and_limit_with_margin(self):
        b = budget.BudgetTracker(0.01, 15.0, margin_usd=0.5, nvm=self._nvm())
        self.assertEqual(b.hard_limit, 14.5)
        self.assertEqual(b.spent_usd(), 0.0)
        self.assertTrue(b.can_query())

    def test_record_increments_spend(self):
        b = budget.BudgetTracker(0.01, 1.0, margin_usd=0.0, nvm=self._nvm())
        b.set_month(100)
        b.record_query()
        b.record_query()
        self.assertEqual(b.count, 2)
        self.assertAlmostEqual(b.spent_usd(), 0.02)

    def test_stops_before_exceeding_budget(self):
        # limit = 1.0 - 0.0 = 1.0; cost 0.50 -> allow at 0, 1 query; block at 2.
        b = budget.BudgetTracker(0.50, 1.0, margin_usd=0.0, nvm=self._nvm())
        self.assertTrue(b.can_query())   # 0 spent + 0.50 <= 1.0
        b.record_query()
        self.assertTrue(b.can_query())   # 0.50 + 0.50 <= 1.0
        b.record_query()
        self.assertFalse(b.can_query())  # 1.00 + 0.50 > 1.0 -> stop

    def test_month_rollover_resets_count(self):
        nvm = self._nvm()
        b = budget.BudgetTracker(0.01, 15.0, nvm=nvm)
        b.set_month(24322)   # e.g. 2026*12 + 10
        b.record_query(); b.record_query()
        self.assertEqual(b.count, 2)
        b.set_month(24323)   # next month
        self.assertEqual(b.count, 0)

    def test_persists_across_restart(self):
        nvm = self._nvm()
        b1 = budget.BudgetTracker(0.01, 15.0, nvm=nvm)
        b1.set_month(24322)
        b1.record_query(); b1.record_query(); b1.record_query()
        # "Reboot": a new tracker reading the same NVM sees the same state.
        b2 = budget.BudgetTracker(0.01, 15.0, nvm=nvm)
        self.assertEqual(b2.month_id, 24322)
        self.assertEqual(b2.count, 3)
        self.assertAlmostEqual(b2.spent_usd(), 0.03)

    def test_same_month_does_not_reset(self):
        nvm = self._nvm()
        b = budget.BudgetTracker(0.01, 15.0, nvm=nvm)
        b.set_month(24322)
        b.record_query()
        b.set_month(24322)  # same month again
        self.assertEqual(b.count, 1)

    def test_no_nvm_still_works_in_memory(self):
        b = budget.BudgetTracker(0.01, 15.0, nvm=None)
        b.set_month(1)
        b.record_query()
        self.assertEqual(b.count, 1)


if __name__ == "__main__":
    unittest.main()
