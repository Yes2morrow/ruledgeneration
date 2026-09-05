"""进程内滑动窗口限流。

生成接口是 CPU 密集型, 一旦被刷会直接打爆实例。这里做按用户 / 按 appid 的粗粒度限流。

注意: 这是**进程内**实现, 多实例时实际阈值会被放宽到约 N 倍(N = 实例数)。
本项目场景下可接受; 若需要精确全局限流, 需引入 Redis(云托管需配 VpcConf)。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    """滑动窗口限流: 每个 key 在 window 秒内最多允许 limit 次。"""

    def __init__(self, limit: int, window: float, max_keys: int = 10000):
        self.limit = limit
        self.window = window
        self.max_keys = max_keys
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > self.window:
                q.popleft()

            if len(q) >= self.limit:
                return False

            q.append(now)

            # 粗略清理, 避免 key 无限增长
            if len(self._hits) > self.max_keys:
                for k in [k for k, v in self._hits.items() if not v]:
                    self._hits.pop(k, None)
            return True

    def retry_after(self, key: str) -> float:
        """建议的重试等待秒数。"""
        now = time.monotonic()
        with self._lock:
            q = self._hits.get(key)
            if not q:
                return 0.0
            return max(0.0, self.window - (now - q[0]))
