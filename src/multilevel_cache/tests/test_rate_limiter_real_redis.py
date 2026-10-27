"""MLC-14 滑窗限流的真实 Redis 实弹测试

fakeredis 无 lupa 时 EVAL 不可执行, 原 MLC-14 修复仅做过 Python 语义等价校验。
本文件在可连真实 Redis 且 EVAL 可用时补实弹验证(台账 D-1):
1. 并发放行数严格不超 max_requests;
2. 被拒绝的请求不计入窗口(ZCARD 不膨胀, 旧 pipeline 实现的单调膨胀 bug 回归红线);
3. 窗口滑动后恢复放行。
环境不满足(无 redis 库 / 连不上 / 无 EVAL)整模块 skip。
"""

import threading
import time
import uuid

import pytest

redis_lib = pytest.importorskip("redis", reason="redis 库未安装")

_REDIS_HOST = "127.0.0.1"
_REDIS_PORT = 6379
_REDIS_DB = 15  # 专用 db, 与本机业务键(db0)隔离


def _make_client():
    try:
        return redis_lib.Redis(
            host=_REDIS_HOST, port=_REDIS_PORT, db=_REDIS_DB,
            socket_connect_timeout=2, decode_responses=True,
        )
    except Exception:
        return None


def _eval_available(client) -> bool:
    try:
        client.ping()
        return client.eval("return 1", 0) == 1
    except Exception:
        return False


_client = _make_client()
pytestmark = pytest.mark.skipif(
    not (_client is not None and _eval_available(_client)),
    reason=f"真实 Redis 不可用或无 EVAL: {_REDIS_HOST}:{_REDIS_PORT}",
)


class _RedisHolder:
    """RateLimiter 期望的 redis_client 包装(仅需 .client 属性)"""

    def __init__(self, client):
        self.client = client


@pytest.fixture
def limiter_factory():
    """构造唯一键 RateLimiter 并在用例后清键"""
    from multilevel_cache.protection import RateLimiter

    made = []

    def _factory(max_requests, window_seconds):
        rl = RateLimiter(
            _RedisHolder(_client),
            key=f"d1test:{uuid.uuid4().hex[:8]}",
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
        made.append(rl.key)
        return rl

    yield _factory
    for key in made:
        _client.delete(f"{key}:default")  # is_allowed 实际写的是 key:identifier


class TestSlidingWindowRealRedis:
    def test_denied_not_counted_in_window(self, limiter_factory):
        """拒绝不入窗: 超限时段的调用不得使 ZCARD 超过 max_requests"""
        rl = limiter_factory(max_requests=3, window_seconds=60)
        results = [rl.is_allowed() for _ in range(6)]
        assert results == [True, True, True, False, False, False]
        # 旧 pipeline 实现(先 zadd 后判定)此处 ZCARD 会膨胀到 6
        assert _client.zcard(f"{rl.key}:default") == 3
        # get_remaining 同步为 0(修复回归红线: 原 get_connection() 实现恒回落 max)
        assert rl.get_remaining() == 0

    def test_window_sliding_recovery(self, limiter_factory):
        """窗口滑动恢复放行: 窗口过期后重新放行"""
        rl = limiter_factory(max_requests=2, window_seconds=2)
        assert rl.is_allowed() is True
        assert rl.is_allowed() is True
        assert rl.is_allowed() is False
        time.sleep(2.2)
        assert rl.is_allowed() is True

    def test_concurrent_never_exceeds_max(self, limiter_factory):
        """并发不超 max_requests: 20 线程同刻抢 5 个额度, 恰好放行 5"""
        rl = limiter_factory(max_requests=5, window_seconds=60)
        results = []
        lock = threading.Lock()

        def worker():
            ok = rl.is_allowed()
            with lock:
                results.append(ok)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sum(results) == 5
        assert len(results) == 20
        assert _client.zcard(f"{rl.key}:default") == 5
