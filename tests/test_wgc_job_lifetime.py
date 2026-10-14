"""Portable Job-close fixture checks; these fakes are not Windows kernel evidence."""
from types import SimpleNamespace
import subprocess
import unittest
from unittest.mock import Mock

from wgc_smoke import verify_owned_job_close


class WgcJobLifetimeFixtureTests(unittest.TestCase):
    def fixture(self, exit_code=0):
        kernel = SimpleNamespace(WaitForSingleObject=Mock(return_value=0))
        job = SimpleNamespace(kernel=kernel, handle=123)
        def close():
            job.handle = None
            return True
        job.close = Mock(side_effect=close)
        process = SimpleNamespace(_handle=456, poll=Mock(side_effect=[None, exit_code]),
                                  wait=Mock(return_value=exit_code), kill=Mock())
        return job, process

    def test_zero_and_nonzero_exit_are_equally_terminated(self):
        for code in (0, 1, 0xFFFFFFFF):
            job, process = self.fixture(code)
            proof = verify_owned_job_close(job, process)
            self.assertEqual(proof['wait_result'], 0)
            self.assertEqual(proof['exit_code'], code)
            self.assertIs(proof['handle_closed'], True)
            job.kernel.WaitForSingleObject.assert_called_once_with(456, 3000)
            process.wait.assert_called_once_with(timeout=0)
            process.kill.assert_not_called()

    def test_already_exited_helper_cannot_prove_job_close(self):
        job, process = self.fixture()
        process.poll = Mock(return_value=0)
        with self.assertRaisesRegex(AssertionError, 'before Job-close'):
            verify_owned_job_close(job, process)
        job.close.assert_not_called()
        job.kernel.WaitForSingleObject.assert_not_called()

    def test_close_failure_or_retained_handle_fails_before_wait(self):
        for returned in (False, True):
            job, process = self.fixture()
            job.close = Mock(return_value=returned)
            with self.assertRaisesRegex(AssertionError, 'handle did not close'):
                verify_owned_job_close(job, process)
            job.kernel.WaitForSingleObject.assert_not_called()
            process.wait.assert_not_called()

    def test_timeout_and_failed_wait_cannot_pass_or_kill_as_evidence(self):
        for status in (258, 0xFFFFFFFF):
            job, process = self.fixture()
            job.kernel.WaitForSingleObject.return_value = status
            with self.assertRaisesRegex(AssertionError, 'did not signal'):
                verify_owned_job_close(job, process)
            process.wait.assert_not_called()
            process.kill.assert_not_called()

    def test_wait_poll_disagreement_fails(self):
        job, process = self.fixture()
        process.poll = Mock(side_effect=[None, None])
        with self.assertRaisesRegex(AssertionError, 'disagree'):
            verify_owned_job_close(job, process)

    def test_popen_timeout_after_signal_is_not_hidden(self):
        job, process = self.fixture()
        process.wait.side_effect = subprocess.TimeoutExpired('owned fixture', 0)
        with self.assertRaises(subprocess.TimeoutExpired):
            verify_owned_job_close(job, process)
        process.kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
