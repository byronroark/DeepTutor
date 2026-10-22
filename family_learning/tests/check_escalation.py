"""No Discord, network, actual package installation or household data."""
import concurrent.futures
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'learning'))
from escalation import Queue


class EscalationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.now = 1000.0
        self.q = Queue(self.temp.name, clock=lambda: self.now)

    def add(self, kind='learning', parent='dad'):
        return self.q.observe('learner-one', kind, 'a' * 32, parent, {'title': 'Fractions'})

    def test_no_early_ping_online_then_exact_three_minutes(self):
        self.add()
        for age in (0, 59, 120, 179):
            self.now = 1000 + age
            self.q.heartbeat('dad')
            self.assertIsNone(self.q.claim())
        self.now = 1180
        self.q.heartbeat('dad')
        self.assertIsNotNone(self.q.claim())

    def test_unknown_desktop_waits_three_minutes(self):
        self.add()
        self.now = 1179
        self.assertIsNone(self.q.claim())
        self.now = 1180
        self.assertIsNotNone(self.q.claim())

    def test_confirmed_offline_escalates_after_heartbeat_grace(self):
        self.q.heartbeat('dad')
        self.add()
        self.now = 1059
        self.assertIsNone(self.q.claim())
        self.now = 1060
        self.assertIsNotNone(self.q.claim())

    def test_online_recovery_keeps_original_three_minute_deadline(self):
        self.q.heartbeat('dad')
        self.add()
        self.now = 1059
        self.q.heartbeat('dad')
        self.assertIsNone(self.q.claim())
        self.now = 1180
        self.q.heartbeat('dad')
        self.assertIsNotNone(self.q.claim())

    def test_desktop_decision_prevents_discord_for_all_kinds(self):
        for kind in ('learning', 'software', 'break'):
            self.add(kind)
            self.q.settle('learner-one', kind, 'a' * 32, 'denied')
        self.now = 2000
        self.assertIsNone(self.q.claim())

    def test_poll_and_restart_do_not_reset_wait(self):
        key = self.add()
        self.now = 1179
        restarted = Queue(self.temp.name, clock=lambda: self.now)
        self.assertEqual(key, restarted.observe('learner-one', 'learning', 'a' * 32, 'dad', {'title': 'Fractions'}))
        self.now = 1180
        self.assertIsNotNone(restarted.claim())

    def test_only_one_sender_wins_concurrent_claim(self):
        self.add()
        self.now = 1200
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.q.claim(), range(4)))
        self.assertEqual(sum(item is not None for item in results), 1)

    def test_sent_card_is_not_sent_again(self):
        self.add()
        self.now = 1200
        lease = self.q.claim()
        self.q.sent(lease['id'], lease['lease'], '123456789012345678')
        self.now = 2000
        self.assertIsNone(self.q.claim())

    def test_delivery_failure_can_retry_after_lease(self):
        self.add()
        self.now = 1200
        first = self.q.claim()
        self.now += 31
        second = self.q.claim()
        self.assertNotEqual(first['lease'], second['lease'])
        with self.assertRaises(ValueError):
            self.q.sent(first['id'], first['lease'], '123456789012345678')

    def test_decision_race_invalidates_pending_delivery(self):
        self.add()
        self.now = 1200
        lease = self.q.claim()
        self.q.settle('learner-one', 'learning', 'a' * 32, 'approved')
        with self.assertRaises(ValueError):
            self.q.sent(lease['id'], lease['lease'], '123456789012345678')

    def test_request_mutation_rejected(self):
        self.add()
        with self.assertRaises(ValueError):
            self.q.observe('learner-one', 'learning', 'a' * 32, 'dad', {'title': 'Changed'})

    def test_one_backend_decision_settles_both_parents(self):
        self.add(parent='dad')
        self.add(parent='mom')
        self.q.settle('learner-one', 'learning', 'a' * 32, 'denied')
        self.now = 1200
        self.assertIsNone(self.q.claim())

    def test_approved_install_waiting_for_worker_does_not_escalate(self):
        self.add('software')
        self.q.settle('learner-one', 'software', 'a' * 32, 'queued')
        self.now = 1200
        self.assertIsNone(self.q.claim())


if __name__ == '__main__':
    unittest.main()
