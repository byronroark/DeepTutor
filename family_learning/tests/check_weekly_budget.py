import concurrent.futures
from datetime import datetime
import pathlib
import sys
import tempfile
import unittest
from zoneinfo import ZoneInfo
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'learning'))
from weekly_budget import Ledger, BudgetExceeded, week_key


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = datetime(2026, 10, 21, 12, tzinfo=ZoneInfo('America/New_York'))
        self.ledger = Ledger(self.temp.name, clock=lambda: self.now, limit=1_000_000)

    def test_admission_reserves_before_usage(self):
        self.ledger.reserve(1000, 1000)
        self.assertEqual(self.ledger.status()['used_nanodollars'], 600_000)
        with self.assertRaises(BudgetExceeded):
            self.ledger.reserve(1000, 1000)

    def test_actual_usage_refunds_only_unused_reservation(self):
        key = self.ledger.reserve(1000, 1000)
        self.assertTrue(self.ledger.reconcile(key, {'prompt_tokens': 100, 'completion_tokens': 100}))
        self.assertEqual(self.ledger.status()['used_nanodollars'], 60_000)
        self.assertFalse(self.ledger.reconcile(key, {'prompt_tokens': 0, 'completion_tokens': 0}))

    def test_missing_or_malformed_usage_keeps_full_reservation(self):
        key = self.ledger.reserve(1000, 1000)
        for bad in (None, {}, {'prompt_tokens': True, 'completion_tokens': 0},
                    {'prompt_tokens': -1, 'completion_tokens': 0}):
            self.assertFalse(self.ledger.reconcile(key, bad))
        self.assertEqual(self.ledger.status()['used_nanodollars'], 600_000)

    def test_restart_preserves_inflight_charge(self):
        self.ledger.reserve(1000, 1000)
        again = Ledger(self.temp.name, clock=lambda: self.now, limit=1_000_000)
        with self.assertRaises(BudgetExceeded):
            again.reserve(1000, 1000)

    def test_concurrency_cannot_overbook(self):
        def attempt(_):
            try:
                self.ledger.reserve(1000, 1000)
                return True
            except BudgetExceeded:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt, range(8))), 1)

    def test_reset_is_eastern_monday_and_no_rollover(self):
        self.ledger.reserve(1000, 1000)
        self.now = datetime(2026, 10, 26, 3, 59, tzinfo=ZoneInfo('UTC'))
        self.assertEqual(self.ledger.status()['used_nanodollars'], 600_000)
        self.now = datetime(2026, 10, 26, 4, 0, tzinfo=ZoneInfo('UTC'))
        self.assertEqual(self.ledger.status()['remaining_nanodollars'], 1_000_000)

    def test_winter_dst_boundary(self):
        self.assertEqual(week_key(datetime(2026, 11, 2, 4, 59, tzinfo=ZoneInfo('UTC'))), '2026-10-26')
        self.assertEqual(week_key(datetime(2026, 11, 2, 5, 0, tzinfo=ZoneInfo('UTC'))), '2026-11-02')

    def test_cross_week_completion_charges_request_week(self):
        key = self.ledger.reserve(1000, 1000)
        self.now = datetime(2026, 10, 26, 12, tzinfo=ZoneInfo('America/New_York'))
        self.ledger.reconcile(key, {'prompt_tokens': 100, 'completion_tokens': 100})
        self.assertEqual(self.ledger.status()['used_nanodollars'], 0)

    def test_oversized_request_and_budget_increase_refused(self):
        with self.assertRaises(ValueError):
            self.ledger.reserve(300_000, 1000)
        with self.assertRaises(ValueError):
            self.ledger.reserve(1000, 10000)
        with self.assertRaises(ValueError):
            Ledger(self.temp.name, limit=6_000_000_000)

    def test_clock_rollback_cannot_reopen_old_budget(self):
        self.ledger.reserve(1000, 1000)
        self.now = datetime(2026, 10, 14, tzinfo=ZoneInfo('UTC'))
        with self.assertRaises(ValueError):
            self.ledger.reserve(100, 100)

    def test_provider_bound_violation_freezes_future_requests(self):
        key = self.ledger.reserve(10, 10)
        self.assertFalse(self.ledger.reconcile(key, {'prompt_tokens': 100, 'completion_tokens': 100}))
        self.assertTrue(self.ledger.status()['review_required'])
        with self.assertRaises(ValueError):
            self.ledger.reserve(10, 10)

if __name__ == '__main__':
    unittest.main()
