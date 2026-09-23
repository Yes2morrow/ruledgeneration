"""Cooperative CPU budget, isolated per worker thread/request."""
from contextvars import ContextVar
import os
import time

_deadline = ContextVar('layout_deadline', default=None)


def start_budget():
    seconds = float(os.environ.get('COMPUTE_TIMEOUT_SECONDS', '300'))
    return _deadline.set(time.monotonic() + seconds)


def reset_budget(token):
    _deadline.reset(token)


def check_budget():
    deadline = _deadline.get()
    if deadline is not None and time.monotonic() > deadline:
        raise TimeoutError('本次计算已达到时间上限，请分区生成或减少模块数量')
