"""Bounded retries for optional client selection, independent of pixel capture."""
import math


class SelectionRetry:
    """A failed optional API must leave time for consecutive pixel observations."""
    def __init__(self):
        self.reset()

    def reset(self):
        self.failures = 0
        self.retry_at = 0.

    def ready(self, now):
        return math.isfinite(now) and now >= self.retry_at

    def failed(self, now):
        if not math.isfinite(now):
            raise ValueError('Expected a finite monotonic time')
        self.failures = min(self.failures + 1, 4)
        self.retry_at = now + min(30., 5. * 2 ** (self.failures - 1))


def selection_capture_status(state):
    """Fixed UI labels describe receipts, never infer capture from the OS border."""
    return {
        'waiting': '选人截图尚未开始',
        'capturing': '正在准备选人截图',
        'captured': '选人截图已收到 · 正在识别英雄',
        'unrecognized': '选人截图成功 · 英雄尚未确认',
        'recognized': '选人截图成功 · 英雄已确认',
        'invalid_result': '选人结果已失效 · 正在重新识别',
        'capture_failed': '选人截图未完成 · 正在重试',
        'recognition_failed': '选人截图成功 · 识别失败，正在重试',
        'interface': '本机选人接口 · 本次无需截图',
        'interface_failed': '选人接口暂不可用 · 等待截图回退',
    }.get(state, '选人采集状态待确认')
