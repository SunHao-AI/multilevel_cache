"""
多级缓存模块单元测试
"""

import pytest
import time
import threading
import uuid
from unittest.mock import Mock, patch, MagicMock

from multilevel_cache.config import (
    CacheConfig,
    MemoryCacheConfig,
    RedisConfig,
    TTLConfig,
    CacheKeyBuilder,
    EvictionPolicy,
)
from multilevel_cache.core import (
    MemoryCache,
    RedisCache,
    MultiLevelCache,
    CacheManager,
    CacheEntry,
)
from multilevel_cache.decorators import cached, cached_async
from multilevel_cache.protection import (
    CacheProtection,
    DistributedLock,
    LocalLock,
    BloomFilter,
    CircuitBreaker,
)
from multilevel_cache.monitoring import CacheMetrics, CacheMonitor


class TestMemoryCache:
    """内存缓存测试"""
    
    def test_basic_operations(self):
        """测试基本操作"""
        config = MemoryCacheConfig(max_size=100, default_ttl=60)
        cache = MemoryCache(config)
        
        assert cache.get("key1") is None
        
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        
        assert cache.delete("key1") is True
        assert cache.get("key1") is None
        
        assert cache.delete("nonexistent") is False
    
    def test_ttl_expiration(self):
        """测试TTL过期"""
        cache = MemoryCache(MemoryCacheConfig(default_ttl=1))
        
        cache.set("key1", "value1", ttl=1)
        assert cache.get("key1") == "value1"
        
        time.sleep(1.5)
        assert cache.get("key1") is None
    
    def test_max_size_eviction(self):
        """测试容量淘汰"""
        cache = MemoryCache(MemoryCacheConfig(max_size=3, eviction_policy=EvictionPolicy.LRU))
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        
        cache.get("key1")
        
        cache.set("key4", "value4")
        
        assert cache.get("key1") == "value1"
        assert cache.get("key4") == "value4"
    
    def test_clear(self):
        """测试清空缓存"""
        cache = MemoryCache()
        
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        cache.clear()
        
        assert cache.get("key1") is None
        assert cache.get("key2") is None
    
    def test_stats(self):
        """测试统计信息"""
        cache = MemoryCache()
        
        cache.set("key1", "value1")
        cache.get("key1")
        cache.get("key1")
        cache.get("nonexistent")
        
        stats = cache.get_stats()
        
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert "hit_rate" in stats
    
    def test_thread_safety(self):
        """测试线程安全"""
        cache = MemoryCache(MemoryCacheConfig(thread_safe=True, max_size=1000))
        
        def writer(start, count):
            for i in range(count):
                cache.set(f"key_{start}_{i}", f"value_{start}_{i}")
        
        threads = [
            threading.Thread(target=writer, args=(i, 100))
            for i in range(10)
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        stats = cache.get_stats()
        assert stats["size"] > 0


class TestCacheConfig:
    """缓存配置测试"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = CacheConfig()
        
        assert config.name == "default"
        assert config.memory_config.max_size == 1000
        assert config.ttl_config.default == 300
    
    def test_config_from_dict(self):
        """测试从字典创建配置"""
        data = {
            "name": "test_cache",
            "memory": {
                "max_size": 500,
                "default_ttl": 120,
            },
            "ttl": {
                "default": 600,
                "l1_ttl": 300,
            },
        }
        
        config = CacheConfig.from_dict(data)
        
        assert config.name == "test_cache"
        assert config.memory_config.max_size == 500
        assert config.ttl_config.default == 600
    
    def test_ttl_jitter(self):
        """测试TTL抖动"""
        config = TTLConfig(jitter_min=0.9, jitter_max=1.1)
        
        ttl = config.get_ttl_with_jitter(100)
        
        assert 90 <= ttl <= 110


class TestCacheKeyBuilder:
    """缓存键构建器测试"""
    
    def test_build_key(self):
        """测试构建缓存键"""
        key = CacheKeyBuilder.build("user", 123)
        
        assert key == "v1:user:123"
    
    def test_build_key_with_extra_parts(self):
        """测试带额外部分的缓存键"""
        key = CacheKeyBuilder.build("user", 123, "profile", "avatar")
        
        assert key == "v1:user:123:profile:avatar"
    
    def test_build_pattern(self):
        """测试构建匹配模式"""
        pattern = CacheKeyBuilder.build_pattern("user")
        
        assert pattern == "v1:user:*"
    
    def test_parse_key(self):
        """测试解析缓存键"""
        result = CacheKeyBuilder.parse("v1:user:123:profile")
        
        assert result["version"] == "v1"
        assert result["prefix"] == "user"
        assert result["identifier"] == "123"
        assert result["extra"] == ["profile"]


class TestCacheProtection:
    """缓存防护测试"""
    
    def test_null_value_detection(self):
        """测试空值检测"""
        protection = CacheProtection()
        
        assert protection.is_null_value("__NULL__") is True
        assert protection.is_null_value("value") is False
    
    def test_ttl_jitter(self):
        """测试TTL抖动"""
        protection = CacheProtection()
        
        ttl = protection.add_jitter(100)
        
        assert 90 <= ttl <= 110
    
    def test_zero_ttl_jitter(self):
        """测试零TTL抖动"""
        protection = CacheProtection()
        
        ttl = protection.add_jitter(0)
        
        assert ttl == 0


class TestLocalLock:
    """本地锁测试"""
    
    def test_acquire_release(self):
        """测试获取和释放锁"""
        lock = LocalLock(timeout=5)
        
        assert lock.acquire() is True
        assert lock._acquired is True
        
        assert lock.release() is True
        assert lock._acquired is False
    
    def test_context_manager(self):
        """测试上下文管理器"""
        lock = LocalLock()
        
        with lock:
            assert lock._acquired is True
        
        assert lock._acquired is False


class TestCircuitBreaker:
    """熔断器测试"""
    
    def test_closed_state(self):
        """测试关闭状态"""
        cb = CircuitBreaker(failure_threshold=3)
        
        assert cb.state == CircuitBreaker.STATE_CLOSED
        assert cb.is_available() is True
    
    def test_open_after_failures(self):
        """测试失败后打开"""
        cb = CircuitBreaker(failure_threshold=2)
        
        cb.record_failure()
        assert cb.state == CircuitBreaker.STATE_CLOSED
        
        cb.record_failure()
        assert cb.state == CircuitBreaker.STATE_OPEN
        assert cb.is_available() is False
    
    def test_recovery(self):
        """测试恢复"""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=1)
        
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.STATE_OPEN
        
        time.sleep(1.5)
        
        assert cb.is_available() is True
        assert cb.state == CircuitBreaker.STATE_HALF_OPEN
        
        cb.record_success()
        cb.record_success()
        cb.record_success()
        assert cb.state == CircuitBreaker.STATE_CLOSED
    
    def test_reset(self):
        """测试重置"""
        cb = CircuitBreaker(failure_threshold=2)
        
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitBreaker.STATE_OPEN
        
        cb.reset()
        assert cb.state == CircuitBreaker.STATE_CLOSED


class TestCacheMetrics:
    """缓存指标测试"""
    
    def test_hit_rate_calculation(self):
        """测试命中率计算"""
        metrics = CacheMetrics()
        
        metrics.l1_hits = 80
        metrics.l1_misses = 20
        
        assert metrics.l1_hit_rate == 80.0
    
    def test_overall_hit_rate(self):
        """测试总体命中率"""
        metrics = CacheMetrics()
        
        metrics.l1_hits = 50
        metrics.l2_hits = 30
        metrics.l3_hits = 10
        metrics.total_requests = 100
        
        assert metrics.overall_hit_rate == 90.0
    
    def test_to_dict(self):
        """测试转换为字典"""
        metrics = CacheMetrics()
        metrics.l1_hits = 10
        metrics.l1_misses = 5
        
        result = metrics.to_dict()
        
        assert result["l1_hits"] == 10
        assert result["l1_misses"] == 5
        assert "l1_hit_rate" in result


class TestCacheMonitor:
    """缓存监控测试"""
    
    def test_record_hit(self):
        """测试记录命中"""
        monitor = CacheMonitor()
        
        monitor.record_hit("l1")
        monitor.record_hit("l2")
        
        assert monitor.metrics.l1_hits == 1
        assert monitor.metrics.l2_hits == 1
        assert monitor.metrics.total_requests == 2
    
    def test_record_miss(self):
        """测试记录未命中"""
        monitor = CacheMonitor()
        
        monitor.record_miss("l1")
        
        assert monitor.metrics.l1_misses == 1
    
    def test_record_error(self):
        """测试记录错误"""
        monitor = CacheMonitor()
        
        monitor.record_error("connection")
        
        assert monitor.metrics.total_errors == 1
    
    def test_get_stats(self):
        """测试获取统计"""
        monitor = CacheMonitor()
        
        monitor.record_hit("l1")
        monitor.record_miss("l1")
        
        stats = monitor.get_stats()
        
        assert "l1_hits" in stats
        assert "l1_misses" in stats
    
    def test_reset(self):
        """测试重置"""
        monitor = CacheMonitor()
        
        monitor.record_hit("l1")
        monitor.record_miss("l1")
        
        monitor.reset()
        
        assert monitor.metrics.l1_hits == 0
        assert monitor.metrics.l1_misses == 0


class TestCachedDecorator:
    """缓存装饰器测试"""

    def test_cached_decorator(self):
        """测试缓存装饰器

        key_prefix 带 uuid: 固定前缀直连真实 Redis 时, TTL 内重跑会被
        上次残留键命中导致 call_count 断言失败(非幂等), 唯一前缀保证可重复运行。
        """
        call_count = 0
        prefix = f"test:{uuid.uuid4().hex[:8]}"

        @cached(key_prefix=prefix, ttl=60)
        def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2

        result1 = expensive_function(5)
        result2 = expensive_function(5)

        assert result1 == 10
        assert result2 == 10
        assert call_count == 1

    def test_cached_with_different_args(self):
        """测试不同参数的缓存(唯一 key_prefix, 同上加幂等)"""
        call_count = 0
        prefix = f"test:{uuid.uuid4().hex[:8]}"

        @cached(key_prefix=prefix)
        def func(x):
            nonlocal call_count
            call_count += 1
            return x

        func(1)
        func(2)
        func(1)

        assert call_count == 2


class TestMultiLevelCache:
    """多级缓存测试"""
    
    def test_l1_cache_only(self):
        """测试仅L1缓存"""
        config = CacheConfig()
        config.degradation_config.enable_l2_fallback = False
        
        cache = MultiLevelCache(config)
        
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
    
    def test_l1_miss_with_loader(self):
        """测试L1未命中时使用loader"""
        config = CacheConfig()
        config.degradation_config.enable_l2_fallback = False
        
        cache = MultiLevelCache(config)
        
        call_count = 0
        
        def loader():
            nonlocal call_count
            call_count += 1
            return "loaded_value"
        
        result = cache.get("key1", loader=loader)
        
        assert result == "loaded_value"
        assert call_count == 1
        
        cache.get("key1", loader=loader)
        assert call_count == 1
    
    def test_cache_disabled(self):
        """测试禁用缓存"""
        config = CacheConfig()
        config.degradation_config.enable_l2_fallback = False
        
        cache = MultiLevelCache(config)
        cache.disable()
        
        call_count = 0
        
        def loader():
            nonlocal call_count
            call_count += 1
            return "value"
        
        cache.set("key1", "value1")
        result = cache.get("key1", loader=loader)
        
        assert result == "value"
        assert call_count == 1
    
    def test_delete_pattern(self):
        """测试模式删除"""
        config = CacheConfig()
        config.degradation_config.enable_l2_fallback = False
        
        cache = MultiLevelCache(config)
        
        cache.set("user:1", "value1")
        cache.set("user:2", "value2")
        cache.set("other:1", "value3")
        
        count = cache.delete_pattern("user:*")
        
        assert count >= 2
        assert cache.get("other:1") == "value3"


class TestCacheManager:
    """缓存管理器测试"""
    
    def test_singleton(self):
        """测试单例模式"""
        manager1 = CacheManager()
        manager2 = CacheManager()
        
        assert manager1 is manager2
    
    def test_basic_operations(self):
        """测试基本操作"""
        manager = CacheManager()
        
        manager.set("key1", "value1")
        assert manager.get("key1") == "value1"
        
        manager.delete("key1")
        assert manager.get("key1") is None
    
    def test_enable_disable(self):
        """测试启用/禁用"""
        manager = CacheManager()
        
        manager.disable()
        assert manager.is_enabled() is False
        
        manager.enable()
        assert manager.is_enabled() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
