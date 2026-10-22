"""Controlled API failure and client-frame timing; no live League connection."""
import unittest

from selection_retry import SelectionRetry, selection_capture_status
from selection_session import SelectionSession


class SelectionRetryTests(unittest.TestCase):
    def test_failed_optional_reads_back_off_and_success_resets(self):
        retry = SelectionRetry()
        self.assertTrue(retry.ready(100.))
        now = 100.
        for delay in (5., 10., 20., 30., 30.):
            retry.failed(now)
            self.assertFalse(retry.ready(now + delay - .001))
            self.assertTrue(retry.ready(now + delay))
            now += delay
        retry.reset()
        self.assertTrue(retry.ready(now))
        retry.failed(now)
        self.assertEqual(retry.retry_at, now + 5.)

    def test_timeout_does_not_interrupt_consecutive_slow_pixel_observations(self):
        client = (1, 2, 'RCLIENT')
        observation = {'scene': 'assigned-selection', 'assigned': True, 'championId': '9001'}

        def replay(backoff):
            session = SelectionSession(); session.start(client)
            retry = SelectionRetry()
            retry.failed(101.8)  # First API request timed out after 1.8 s.
            now = 102.
            for _ in range(2):
                captured_at = now
                session.observe_client(observation, client, captured_at, now + 2.5,
                                       generation=session.generation)
                now += 2.7  # 2.5 s OCR and a 200 ms scheduling gap.
                if not backoff or retry.ready(now):
                    now += 1.8
                    retry.failed(now)
                    now += .2
            return session

        self.assertEqual(replay(False).candidate_frames, 1)
        recovered = replay(True)
        self.assertEqual(recovered.candidate_frames, 2)
        self.assertEqual(recovered.assigned, '9001')

    def test_capture_status_requires_explicit_receipt(self):
        self.assertIn('尚未开始', selection_capture_status('waiting'))
        self.assertNotIn('成功', selection_capture_status('capturing'))
        self.assertIn('已收到', selection_capture_status('captured'))
        self.assertIn('截图成功', selection_capture_status('unrecognized'))
        self.assertIn('识别失败', selection_capture_status('recognition_failed'))
        self.assertIn('未完成', selection_capture_status('capture_failed'))
        self.assertIn('无需截图', selection_capture_status('interface'))
        self.assertIn('已失效', selection_capture_status('invalid_result'))
        self.assertNotIn('截图', selection_capture_status('invalid_result'))
        self.assertNotIn('PRIVATE', selection_capture_status('PRIVATE'))


if __name__ == '__main__':
    unittest.main()
