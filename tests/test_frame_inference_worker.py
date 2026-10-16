"""Portable same-frame concurrency/cleanup, not Windows timing evidence."""
import threading
import unittest
from frame_inference_worker import FrameInferenceWorker

class FrameInferenceWorkerTests(unittest.TestCase):
    def test_reuses_one_daemon_and_propagates_errors_without_poisoning(self):
        worker=FrameInferenceWorker();self.addCleanup(worker.close)
        ids=[worker.submit(threading.get_ident).result(2) for _ in range(20)]
        self.assertEqual(len(set(ids)),1);self.assertTrue(worker._thread.daemon)
        def fail():raise ValueError('owned error')
        with self.assertRaisesRegex(ValueError,'owned error'):worker.submit(fail).result(2)
        self.assertEqual(worker.submit(threading.get_ident).result(2),ids[0])

    def test_at_most_one_inflight_close_does_not_wait_and_revokes_submit(self):
        worker=FrameInferenceWorker();release=threading.Event();entered=threading.Event()
        self.addCleanup(release.set);self.addCleanup(worker.close)
        def held():entered.set();release.wait(3);return 42
        future=worker.submit(held);self.assertTrue(entered.wait(2))
        self.assertFalse(future.cancel())
        with self.assertRaisesRegex(RuntimeError,'in flight'):worker.submit(lambda:1)
        worker.close()
        with self.assertRaisesRegex(RuntimeError,'closed'):worker.submit(lambda:1)
        self.assertFalse(future.done());release.set();self.assertEqual(future.result(2),42)
        worker._thread.join(2);self.assertFalse(worker._thread.is_alive())

    def test_close_drains_submission_accepted_by_completion_callback(self):
        worker=FrameInferenceWorker();release=threading.Event();queued=[]
        self.addCleanup(release.set);self.addCleanup(worker.close)
        first=worker.submit(lambda:release.wait(2))
        def completed(future):
            queued.append(worker.submit(lambda:42));worker.close()
        first.add_done_callback(completed);release.set();first.result(2)
        worker._thread.join(2)
        self.assertFalse(worker._thread.is_alive());self.assertEqual(len(queued),1)
        self.assertEqual(queued[0].result(2),42);self.assertFalse(worker._busy)

    def test_close_idle_and_unused_worker(self):
        worker=FrameInferenceWorker();worker.close();self.assertIsNone(worker._thread)
        worker=FrameInferenceWorker();worker.submit(lambda:None).result(2)
        worker.close();worker._thread.join(2);self.assertFalse(worker._thread.is_alive())


class SameFrameParallelTests(unittest.TestCase):
    def setUp(self):
        from hero_recognition import PortraitMatcher
        from synthetic_vision import portraits,frame,encoded
        self.worker=FrameInferenceWorker();self.addCleanup(self.worker.close)
        bank=portraits();self.image=encoded(frame(bank['9001']))
        self.matcher=PortraitMatcher(bank,{'owned':{'championId':'9001'}})

    def test_independent_ocr_starts_during_hud_and_both_join_before_return(self):
        from hero_recognition import recognize_frame
        entered=threading.Event();matched=threading.Event()
        class OCR:
            def recognize(inner,payload,vocabulary):
                entered.set()
                if not matched.wait(2):raise AssertionError('HUD did not run concurrently')
                return {'ocr_lines':[]}
        def match(prepared):
            self.assertTrue(entered.wait(2));matched.set();return {'hero':'owned','confident':True}
        self.matcher._recognize_prepared=match
        result=recognize_frame(self.image,(.15,.25,.7,.35),OCR(),(),self.matcher,inference_worker=self.worker)
        self.assertEqual(result['hero_observation']['hero'],'owned')
        self.assertFalse(self.worker._busy)

    def test_failed_callback_still_drains_same_frame_ocr(self):
        from hero_recognition import recognize_frame
        entered=threading.Event();proof=threading.Event();done=threading.Event()
        class OCR:
            def recognize(inner,payload,vocabulary):
                entered.set();proof.wait(2);done.set();return {'ocr_lines':[]}
        def after(hero,crop):
            self.assertTrue(entered.wait(2));proof.set();raise ValueError('proof revoked')
        with self.assertRaisesRegex(ValueError,'proof revoked'):
            recognize_frame(self.image,(.15,.25,.7,.35),OCR(),(),self.matcher,before_ocr=after,inference_worker=self.worker)
        self.assertTrue(done.is_set());self.assertFalse(self.worker._busy)
        self.assertEqual(self.worker.submit(lambda:42).result(2),42)

if __name__=='__main__':unittest.main()
