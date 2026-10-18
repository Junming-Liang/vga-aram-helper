"""Bound idle time using measured work, without extending display authority."""
import math


def next_capture_delay(base_ms, age_seconds, timings):
    """Reserve the previous frame's work plus a margin inside the 4s deadline.

    This is a scheduling estimate, never evidence that the next frame is fresh.
    A slower next frame still expires normally. Keep at least 50ms idle to avoid
    a zero-delay retry loop; callers retain explicit error/backoff intervals.
    """
    if not isinstance(age_seconds, (int, float)) or not math.isfinite(age_seconds) or not 0 <= age_seconds <= 4:
        return base_ms
    cost = 0.
    if isinstance(timings, dict):
        values = [timings.get(key) for key in ('capture_ms', 'inference_ms')]
        if all(isinstance(value, (int, float)) and not isinstance(value, bool)
               and math.isfinite(value) and value >= 0 for value in values):
            cost = min(8000., sum(values))
    margin = max(80., cost * .1)
    remaining = (4 - age_seconds) * 1000 - cost - margin
    return min(base_ms, max(50, int(remaining)))
