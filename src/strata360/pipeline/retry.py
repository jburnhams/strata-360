"""Retrying stage items. Every stage retries a failed item `Stage.retries` times (default 2; the paid transcript check has 100: it fights overloaded APIs, and every call that did succeed is cached, so each
retry only repeats what is missing). A retry waits a little longer each time. An error can say it is not worth retrying (`retryable = False`: a rejected API key, a missing file), and an attempt that
made progress (`progress = True`: some of the calls worked) does not use up a retry. The state of an item that is waiting is `status: 'retry'` in the clip's stages.json."""
import random, time

BASE_WAIT_S = 15.0; MAX_WAIT_S = 600.0


PROGRAMMING_ERRORS = (TypeError, NameError, AttributeError, ImportError, SyntaxError, AssertionError, NotImplementedError)       # failures of the code itself: never retried


PROGRESS_WAIT_S = 1.0           # seconds to wait before the next try after an attempt that made progress (it does not use up a retry, so it is soon)


class RetryLater(Exception):
    """Raised by a stage when part of the work failed for now (overloaded service, network): what worked is kept, the item is tried again later."""
    retryable = True
    def __init__(self, msg, progress=False): super().__init__(msg); self.progress = bool(progress)


def backoff_s(attempts, jitter=0.0):
    """Exponential backoff: seconds to wait before the next try after `attempts` failures without progress (15, 30, 60, 120 ... up to 10 minutes), plus up to `jitter` (a fraction) more at random so
    items that failed together do not all come back at the same moment."""
    w = min(BASE_WAIT_S * 2 ** max(int(attempts) - 1, 0), MAX_WAIT_S)
    return w * (1.0 + jitter * random.random())


def next_state(prev, error, retryable, progress, retries, now=None):
    """The state entry after a failure: ('retry', entry) while retries are left, else ('failed', entry). `prev` is the item's previous retry entry (or None)."""
    now = now if now is not None else time.time(); prev = prev or {}
    attempts = int(prev.get('attempts', 0)) + (0 if progress else 1); total = int(prev.get('total_attempts', 0)) + 1
    base = dict(attempts=attempts, total_attempts=total, last_error=str(error)[-300:], first_failure_at=prev.get('first_failure_at', now), last_attempt_at=now, retries=retries)
    if not retryable or attempts > retries: return 'failed', base
    wait = PROGRESS_WAIT_S if progress else backoff_s(attempts, 0.2)
    return 'retry', dict(base, wait_s=round(wait, 1), next_try_at=now + wait)                 # wait_s: the sleep chosen for this retry (shown in the app with the time left)
