"""
模块验证脚本
直接测试模块功能，不依赖pytest
"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from multilevel_cache.config import (
    CacheConfig, 
    MemoryCacheConfig, 
    TTLConfig,
    CacheKeyBuilder,
    EvictionPolicy,
    DegradationConfig,
)
from multilevel_cache.core import (
    MemoryCache,
    MultiLevelCache,
    CacheManager,
)
from multilevel_cache.protection import (
    CacheProtection,
    LocalLock,
    CircuitBreaker,
)
from multilevel_cache.monitoring import (
    CacheMetrics,
    CacheMonitor,
)


def test_memory_cache():
    """测试内存缓存"""
    print("\n=== 测试内存缓存 ===")
    
    config = MemoryCacheConfig(max_size=100, default_ttl=60)
    cache = MemoryCache(config)
    
    cache.set('key1', 'value1')
    assert cache.get('key1') == 'value1', 'set/get测试失败'
    print('[OK] set/get: 通过')
    
    assert cache.delete('key1') == True, 'delete测试失败'
    assert cache.get('key1') is None, 'delete后get测试失败'
    print('[OK] delete: 通过')
    
    stats_cache = MemoryCache(MemoryCacheConfig(max_size=100, default_ttl=60))
    stats_cache.set('key_stats', 'value_stats')
    stats_cache.get('key_stats')
    stats_cache.get('nonexistent')
    stats = stats_cache.get_stats()
    assert stats['hits'] == 1, f'hits统计错误: hits={stats["hits"]}, expected 1'
    assert stats['misses'] == 1, f'misses统计错误: misses={stats["misses"]}, expected 1'
    print('[OK] stats: 通过')
    
    cache.set('key3', 'value3')
    cache.clear()
    assert cache.get('key3') is None
    print('[OK] clear: 通过')
    
    ttl_cache = MemoryCache(MemoryCacheConfig(max_size=100, default_ttl=60))
    ttl_cache.set('expire_key', 'value', ttl=1)
    assert ttl_cache.get('expire_key') == 'value'
    time.sleep(1.5)
    assert ttl_cache.get('expire_key') is None
    print('[OK] TTL expiration: 通过')


def test_cache_key_builder():
    """测试缓存键构建器"""
    print("\n=== 测试缓存键构建器 ===")
    
    key = CacheKeyBuilder.build('user', 123)
    assert key == 'v1:user:123', f'键构建错误: {key}'
    print('[OK] build: 通过')
    
    key_with_extra = CacheKeyBuilder.build('user', 123, 'profile', 'avatar')
    assert key_with_extra == 'v1:user:123:profile:avatar'
    print('[OK] build with extra: 通过')
    
    pattern = CacheKeyBuilder.build_pattern('user')
    assert pattern == 'v1:user:*', f'模式构建错误: {pattern}'
    print('[OK] build_pattern: 通过')
    
    parts = CacheKeyBuilder.parse('v1:user:123:profile')
    assert parts['version'] == 'v1'
    assert parts['prefix'] == 'user'
    assert parts['identifier'] == '123'
    assert parts['extra'] == ['profile']
    print('[OK] parse: 通过')


def test_cache_protection():
    """测试缓存防护"""
    print("\n=== 测试缓存防护 ===")
    
    protection = CacheProtection()
    
    assert protection.is_null_value('__NULL__') == True
    assert protection.is_null_value('value') == False
    print('[OK] null_value检测: 通过')
    
    for _ in range(10):
        ttl = protection.add_jitter(100)
        assert 90 <= ttl <= 110, f'TTL抖动范围错误: {ttl}'
    print('[OK] TTL抖动: 通过')


def test_local_lock():
    """测试本地锁"""
    print("\n=== 测试本地锁 ===")
    
    lock = LocalLock(timeout=5)
    
    assert lock.acquire() == True
    assert lock._acquired == True
    print('[OK] acquire: 通过')
    
    assert lock.release() == True
    assert lock._acquired == False
    print('[OK] release: 通过')
    
    with LocalLock() as l:
        assert l._acquired == True
    print('[OK] context manager: 通过')


def test_circuit_breaker():
    """测试熔断器"""
    print("\n=== 测试熔断器 ===")
    
    cb = CircuitBreaker(failure_threshold=3)
    
    assert cb.state == "closed"
    assert cb.is_available() == True
    print('[OK] initial state: 通过')
    
    cb.record_failure()
    assert cb.state == "closed"
    print('[OK] first failure: 通过')
    
    cb.record_failure()
    cb.record_failure()
    assert cb.state == "open"
    assert cb.is_available() == False
    print('[OK] open after failures: 通过')
    
    cb.reset()
    assert cb.state == "closed"
    print('[OK] reset: 通过')


def test_cache_metrics():
    """测试缓存指标"""
    print("\n=== 测试缓存指标 ===")
    
    metrics = CacheMetrics()
    
    metrics.l1_hits = 80
    metrics.l1_misses = 20
    
    assert metrics.l1_hit_rate == 80.0, f'命中率计算错误: {metrics.l1_hit_rate}'
    print('[OK] hit_rate: 通过')
    
    result = metrics.to_dict()
    assert 'l1_hits' in result
    assert 'l1_hit_rate' in result
    print('[OK] to_dict: 通过')


def test_cache_monitor():
    """测试缓存监控"""
    print("\n=== 测试缓存监控 ===")
    
    monitor = CacheMonitor()
    
    monitor.record_hit('l1')
    monitor.record_miss('l1')
    
    assert monitor.metrics.l1_hits == 1
    assert monitor.metrics.l1_misses == 1
    print('[OK] record operations: 通过')
    
    stats = monitor.get_stats()
    assert 'l1_hits' in stats
    assert 'l1_misses' in stats
    print('[OK] get_stats: 通过')


def test_multi_level_cache():
    """测试多级缓存"""
    print("\n=== 测试多级缓存 ===")
    
    config = CacheConfig()
    config.degradation_config.enable_l2_fallback = False
    
    cache = MultiLevelCache(config)
    
    cache.set('test_key', 'test_value')
    assert cache.get('test_key') == 'test_value'
    print('[OK] set/get: 通过')
    
    cache.delete('test_key')
    assert cache.get('test_key') is None
    print('[OK] delete: 通过')
    
    stats = cache.get_stats()
    assert 'enabled' in stats
    assert 'l1_stats' in stats
    print('[OK] get_stats: 通过')


def test_cache_manager():
    """测试缓存管理器"""
    print("\n=== 测试缓存管理器 ===")
    
    manager1 = CacheManager()
    manager2 = CacheManager()
    assert manager1 is manager2
    print('[OK] singleton: 通过')
    
    manager1.set('mgr_key', 'mgr_value')
    assert manager1.get('mgr_key') == 'mgr_value'
    print('[OK] set/get: 通过')
    
    manager1.delete('mgr_key')
    assert manager1.get('mgr_key') is None
    print('[OK] delete: 通过')
    
    manager1.disable()
    stats = manager1.get_stats()
    assert stats['enabled'] == False
    manager1.enable()
    stats = manager1.get_stats()
    assert stats['enabled'] == True
    print('[OK] enable/disable: 通过')


def test_thread_safety():
    """测试线程安全"""
    print("\n=== 测试线程安全 ===")
    
    cache = MemoryCache(MemoryCacheConfig(thread_safe=True, max_size=1000))
    
    errors = []
    
    def writer(start, count):
        try:
            for i in range(count):
                cache.set(f'key_{start}_{i}', f'value_{start}_{i}')
        except Exception as e:
            errors.append(str(e))
    
    threads = [
        threading.Thread(target=writer, args=(i, 100))
        for i in range(10)
    ]
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    assert len(errors) == 0, f'线程安全错误: {errors}'
    stats = cache.get_stats()
    assert stats['size'] > 0
    print('[OK] thread safety: 通过')


def run_all_tests():
    """运行所有测试"""
    print("=" * 50)
    print("开始运行多级缓存模块测试")
    print("=" * 50)
    
    try:
        test_memory_cache()
        test_cache_key_builder()
        test_cache_protection()
        test_local_lock()
        test_circuit_breaker()
        test_cache_metrics()
        test_cache_monitor()
        test_multi_level_cache()
        test_cache_manager()
        test_thread_safety()
        
        print("\n" + "=" * 50)
        print("[SUCCESS] 所有测试通过!")
        print("=" * 50)
        return True
        
    except AssertionError as e:
        print(f"\n[FAILED] 测试失败: {str(e)}")
        return False
    except Exception as e:
        print(f"\n[ERROR] 测试异常: {str(e)}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)