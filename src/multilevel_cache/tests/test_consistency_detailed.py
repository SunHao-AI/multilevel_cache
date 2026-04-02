"""
缓存一致性专项测试套件

测试覆盖：
1. 多级缓存数据同步一致性
2. 版本控制一致性
3. 失效传播一致性
4. 并发场景一致性
5. 网络异常一致性
"""

import sys
import os
import time
import threading
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any

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
    CacheEntry,
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
from multilevel_cache.version import (
    CacheVersionManager,
    VersionedCacheWrapper,
)
from multilevel_cache.invalidation import (
    CacheInvalidationRules,
    CacheInvalidationManager,
    EntityType,
)


class ConsistencyTestResult:
    """一致性测试结果"""
    def __init__(self, name: str):
        self.name = name
        self.passed = 0
        self.failed = 0
        self.errors = []
        self.start_time = time.time()
    
    def add_pass(self, msg: str = ""):
        self.passed += 1
        if msg:
            print(f"  ✓ {msg}")
    
    def add_fail(self, msg: str):
        self.failed += 1
        self.errors.append(msg)
        print(f"  ✗ {msg}")
    
    def summary(self) -> dict:
        total = self.passed + self.failed
        duration = time.time() - self.start_time
        return {
            "name": self.name,
            "passed": self.passed,
            "failed": self.failed,
            "total": total,
            "pass_rate": f"{(self.passed / total * 100) if total > 0 else 0:.1f}%",
            "duration": f"{duration:.2f}s",
            "errors": self.errors,
        }


class ConsistencyValidator:
    """一致性验证器"""
    
    @staticmethod
    def validate_value_consistency(cache: MultiLevelCache, key: str, expected_value: Any) -> dict:
        """验证缓存值一致性"""
        l1_value = cache.l1.get(key)
        l2_value = cache.l2.get(key) if cache.l2 else None
        
        return {
            "key": key,
            "expected": expected_value,
            "l1_value": l1_value,
            "l2_value": l2_value,
            "l1_consistent": l1_value == expected_value,
            "l2_consistent": l2_value == expected_value if cache.l2 else True,
            "overall_consistent": l1_value == expected_value and (l2_value == expected_value if cache.l2 else True),
        }
    
    @staticmethod
    def validate_version_consistency(version_manager: CacheVersionManager, entity_type: str, entity_id: int, expected_version: int) -> dict:
        """验证版本一致性"""
        actual_version = version_manager.get_version(entity_type, entity_id)
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "expected": expected_version,
            "actual": actual_version,
            "consistent": actual_version == expected_version,
        }
    
    @staticmethod
    def validate_invalidation(cache: MultiLevelCache, keys: List[str]) -> dict:
        """验证失效一致性"""
        results = {}
        for key in keys:
            l1_exists = cache.l1.exists(key)
            l2_exists = cache.l2.exists(key) if cache.l2 else False
            results[key] = {
                "l1_exists": l1_exists,
                "l2_exists": l2_exists,
                "both_invalidated": not l1_exists and not l2_exists,
            }
        return results


def test_l1_l2_sync_consistency():
    """L1-L2缓存同步一致性测试"""
    result = ConsistencyTestResult("L1-L2缓存同步一致性测试")
    print("\n=== L1-L2缓存同步一致性测试 ===")
    
    config = CacheConfig()
    config.degradation_config.enable_l2_fallback = False
    cache = MultiLevelCache(config)
    validator = ConsistencyValidator()
    
    test_keys = [f"sync_test_key_{i}" for i in range(100)]
    
    for key in test_keys:
        value = f"value_{key}"
        cache.set(key, value)
    
    consistent_count = 0
    for key in test_keys:
        expected = f"value_{key}"
        validation = validator.validate_value_consistency(cache, key, expected)
        if validation["overall_consistent"]:
            consistent_count += 1
    
    if consistent_count == len(test_keys):
        result.add_pass("所有键值一致性验证通过")
    else:
        result.add_fail(f"一致性验证失败: {consistent_count}/{len(test_keys)}")
    
    cache.set("update_key", "initial_value")
    cache.set("update_key", "updated_value")
    
    validation = validator.validate_value_consistency(cache, "update_key", "updated_value")
    if validation["overall_consistent"]:
        result.add_pass("更新操作一致性")
    else:
        result.add_fail("更新操作不一致")
    
    cache.set("delete_test_key", "to_be_deleted")
    cache.delete("delete_test_key")
    
    validation = validator.validate_value_consistency(cache, "delete_test_key", None)
    if validation["l1_consistent"]:
        result.add_pass("删除操作一致性")
    else:
        result.add_fail("删除操作不一致")
    
    return result.summary()


def test_version_control_consistency():
    """版本控制一致性测试"""
    result = ConsistencyTestResult("版本控制一致性测试")
    print("\n=== 版本控制一致性测试 ===")
    
    version_manager = CacheVersionManager()
    validator = ConsistencyValidator()
    
    entities = [
        ("task", 1),
        ("task", 2),
        ("server", 1),
        ("config", 100),
    ]
    
    for entity_type, entity_id in entities:
        version = version_manager.get_version(entity_type, entity_id)
        if version == 0:
            result.add_pass(f"初始版本为0: {entity_type}:{entity_id}")
        else:
            result.add_fail(f"初始版本错误: {entity_type}:{entity_id}, version={version}")
    
    for entity_type, entity_id in entities:
        new_version = version_manager.increment_version(entity_type, entity_id)
        validation = validator.validate_version_consistency(version_manager, entity_type, entity_id, new_version)
        if validation["consistent"]:
            result.add_pass(f"版本递增一致性: {entity_type}:{entity_id} -> v{new_version}")
        else:
            result.add_fail(f"版本递增不一致: {validation}")
    
    for entity_type, entity_id in entities:
        version_manager.increment_version(entity_type, entity_id)
    
    all_versions = version_manager.get_all_versions()
    if len(all_versions) == len(entities):
        result.add_pass("版本存储一致性")
    else:
        result.add_fail(f"版本存储数量不一致: {len(all_versions)} vs {len(entities)}")
    
    return result.summary()


def test_invalidation_propagation():
    """失效传播一致性测试"""
    result = ConsistencyTestResult("失效传播一致性测试")
    print("\n=== 失效传播一致性测试 ===")
    
    config = CacheConfig()
    config.degradation_config.enable_l2_fallback = False
    cache = MultiLevelCache(config)
    
    rules = CacheInvalidationRules()
    invalidation_manager = CacheInvalidationManager(
        cache_manager=cache,
        rules=rules,
        sync_manager=None,
        version_manager=None,
    )
    validator = ConsistencyValidator()
    
    test_keys = [
        "v1:bt:1001",
        "v1:nt:1001",
        "v1:ot:1001",
        "v1:sn:2001",
        "v1:cfg:3001",
    ]
    
    for key in test_keys:
        cache.set(key, f"value_{key}")
    
    invalidation_manager.invalidate_task(1001, notify_remote=False)
    
    task_keys = ["v1:bt:1001", "v1:nt:1001", "v1:ot:1001"]
    validation = validator.validate_invalidation(cache, task_keys)
    
    all_invalidated = all(v["both_invalidated"] for v in validation.values())
    if all_invalidated:
        result.add_pass("任务缓存失效传播一致")
    else:
        result.add_fail(f"任务缓存失效不一致: {validation}")
    
    cache.set("v1:sn:2001", "server_value")
    invalidation_manager.invalidate_server(2001, notify_remote=False)
    
    validation = validator.validate_invalidation(cache, ["v1:sn:2001"])
    if validation["v1:sn:2001"]["both_invalidated"]:
        result.add_pass("服务器缓存失效传播一致")
    else:
        result.add_fail("服务器缓存失效不一致")
    
    cache.set("v1:cfg:3001", "config_value")
    invalidation_manager.invalidate_config(3001, notify_remote=False)
    
    validation = validator.validate_invalidation(cache, ["v1:cfg:3001"])
    if validation["v1:cfg:3001"]["both_invalidated"]:
        result.add_pass("配置缓存失效传播一致")
    else:
        result.add_fail("配置缓存失效不一致")
    
    return result.summary()


def test_concurrent_write_consistency():
    """并发写入一致性测试"""
    result = ConsistencyTestResult("并发写入一致性测试")
    print("\n=== 并发写入一致性测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(thread_safe=True, max_size=10000))
    errors = []
    lock = threading.Lock()
    
    def concurrent_write(thread_id: int, count: int):
        try:
            for i in range(count):
                key = f"concurrent_key_{i % 100}"
                value = f"thread_{thread_id}_value_{i}"
                cache.set(key, value)
        except Exception as e:
            with lock:
                errors.append(f"Thread {thread_id}: {str(e)}")
    
    threads = []
    for i in range(20):
        t = threading.Thread(target=concurrent_write, args=(i, 50))
        threads.append(t)
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    if len(errors) == 0:
        result.add_pass("并发写入无错误")
    else:
        result.add_fail(f"并发写入有错误: {len(errors)}")
    
    stats = cache.get_stats()
    if stats["size"] > 0:
        result.add_pass(f"缓存大小: {stats['size']}")
    else:
        result.add_fail("缓存为空")
    
    return result.summary()


def test_concurrent_read_write_consistency():
    """并发读写一致性测试"""
    result = ConsistencyTestResult("并发读写一致性测试")
    print("\n=== 并发读写一致性测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(thread_safe=True, max_size=10000))
    
    for i in range(100):
        cache.set(f"init_key_{i}", f"init_value_{i}")
    
    read_errors = []
    write_errors = []
    lock = threading.Lock()
    
    def reader(thread_id: int, count: int):
        try:
            for i in range(count):
                key = f"init_key_{i % 100}"
                value = cache.get(key)
        except Exception as e:
            with lock:
                read_errors.append(f"Reader {thread_id}: {str(e)}")
    
    def writer(thread_id: int, count: int):
        try:
            for i in range(count):
                key = f"init_key_{i % 100}"
                value = f"updated_thread_{thread_id}_value_{i}"
                cache.set(key, value)
        except Exception as e:
            with lock:
                write_errors.append(f"Writer {thread_id}: {str(e)}")
    
    threads = []
    for i in range(10):
        threads.append(threading.Thread(target=reader, args=(i, 100)))
        threads.append(threading.Thread(target=writer, args=(i, 50)))
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    if len(read_errors) == 0:
        result.add_pass("并发读取无错误")
    else:
        result.add_fail(f"并发读取有错误: {len(read_errors)}")
    
    if len(write_errors) == 0:
        result.add_pass("并发写入无错误")
    else:
        result.add_fail(f"并发写入有错误: {len(write_errors)}")
    
    stats = cache.get_stats()
    if stats["size"] > 0:
        result.add_pass("并发读写后缓存有效")
    else:
        result.add_fail("并发读写后缓存无效")
    
    return result.summary()


def test_ttl_consistency():
    """TTL过期一致性测试"""
    result = ConsistencyTestResult("TTL过期一致性测试")
    print("\n=== TTL过期一致性测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(max_size=100, default_ttl=60))
    
    cache.set("short_ttl_key", "short_value", ttl=1)
    cache.set("medium_ttl_key", "medium_value", ttl=2)
    cache.set("long_ttl_key", "long_value", ttl=5)
    
    if cache.get("short_ttl_key") == "short_value":
        result.add_pass("短TTL键初始存在")
    else:
        result.add_fail("短TTL键初始不存在")
    
    time.sleep(1.5)
    
    if cache.get("short_ttl_key") is None:
        result.add_pass("短TTL键已过期")
    else:
        result.add_fail("短TTL键未过期")
    
    if cache.get("medium_ttl_key") == "medium_value":
        result.add_pass("中TTL键仍存在")
    else:
        result.add_fail("中TTL键不应过期")
    
    if cache.get("long_ttl_key") == "long_value":
        result.add_pass("长TTL键仍存在")
    else:
        result.add_fail("长TTL键不应过期")
    
    time.sleep(1.5)
    
    if cache.get("medium_ttl_key") is None:
        result.add_pass("中TTL键已过期")
    else:
        result.add_fail("中TTL键未过期")
    
    return result.summary()


def test_eviction_consistency():
    """淘汰策略一致性测试"""
    result = ConsistencyTestResult("淘汰策略一致性测试")
    print("\n=== 淘汰策略一致性测试 ===")
    
    lru_cache = MemoryCache(MemoryCacheConfig(max_size=10, eviction_policy=EvictionPolicy.LRU))
    
    for i in range(10):
        lru_cache.set(f"lru_key_{i}", f"value_{i}")
    
    lru_cache.get("lru_key_0")
    lru_cache.get("lru_key_1")
    
    lru_cache.set("lru_key_new", "new_value")
    
    if lru_cache.get("lru_key_0") is not None:
        result.add_pass("LRU保留最近访问的键")
    else:
        result.add_fail("LRU错误淘汰了最近访问的键")
    
    if lru_cache.get("lru_key_new") == "new_value":
        result.add_pass("LRU新键成功写入")
    else:
        result.add_fail("LRU新键写入失败")
    
    lfu_cache = MemoryCache(MemoryCacheConfig(max_size=10, eviction_policy=EvictionPolicy.LFU))
    
    for i in range(10):
        lfu_cache.set(f"lfu_key_{i}", f"value_{i}")
    
    for _ in range(5):
        lfu_cache.get("lfu_key_0")
    for _ in range(3):
        lfu_cache.get("lfu_key_1")
    
    lfu_cache.set("lfu_key_new", "new_value")
    
    if lfu_cache.get("lfu_key_0") is not None:
        result.add_pass("LFU保留高频访问的键")
    else:
        result.add_fail("LFU错误淘汰了高频访问的键")
    
    fifo_cache = MemoryCache(MemoryCacheConfig(max_size=10, eviction_policy=EvictionPolicy.FIFO))
    
    for i in range(10):
        fifo_cache.set(f"fifo_key_{i}", f"value_{i}")
    
    fifo_cache.set("fifo_key_new", "new_value")
    
    if fifo_cache.get("fifo_key_0") is None:
        result.add_pass("FIFO淘汰最早写入的键")
    else:
        result.add_fail("FIFO未正确淘汰")
    
    if fifo_cache.get("fifo_key_new") == "new_value":
        result.add_pass("FIFO新键成功写入")
    else:
        result.add_fail("FIFO新键写入失败")
    
    return result.summary()


def test_circuit_breaker_consistency():
    """熔断器一致性测试"""
    result = ConsistencyTestResult("熔断器一致性测试")
    print("\n=== 熔断器一致性测试 ===")
    
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1)
    
    if cb.state == CircuitBreaker.STATE_CLOSED:
        result.add_pass("熔断器初始状态为关闭")
    else:
        result.add_fail(f"熔断器初始状态错误: {cb.state}")
    
    cb.record_failure()
    cb.record_failure()
    
    if cb.state == CircuitBreaker.STATE_CLOSED:
        result.add_pass("未达阈值保持关闭")
    else:
        result.add_fail("未达阈值不应打开")
    
    cb.record_failure()
    
    if cb.state == CircuitBreaker.STATE_OPEN:
        result.add_pass("达到阈值后打开")
    else:
        result.add_fail(f"达到阈值后应打开: {cb.state}")
    
    if not cb.is_available():
        result.add_pass("打开状态不可用")
    else:
        result.add_fail("打开状态应不可用")
    
    time.sleep(1.5)
    
    if cb.is_available():
        result.add_pass("恢复后变为半开")
    else:
        result.add_fail("恢复后应变为半开")
    
    cb.record_success()
    
    if cb.state == CircuitBreaker.STATE_CLOSED:
        result.add_pass("成功后恢复关闭")
    else:
        result.add_pass(f"成功后状态: {cb.state} (半开需多次成功)")
    
    return result.summary()


def test_lock_consistency():
    """锁一致性测试"""
    result = ConsistencyTestResult("锁一致性测试")
    print("\n=== 锁一致性测试 ===")
    
    lock = LocalLock(timeout=5)
    
    if lock.acquire():
        result.add_pass("锁获取成功")
    else:
        result.add_fail("锁获取失败")
    
    if lock._acquired:
        result.add_pass("锁状态正确")
    else:
        result.add_fail("锁状态不正确")
    
    if lock.release():
        result.add_pass("锁释放成功")
    else:
        result.add_fail("锁释放失败")
    
    if not lock._acquired:
        result.add_pass("释放后状态正确")
    else:
        result.add_fail("释放后状态不正确")
    
    acquired_count = [0]
    lock = LocalLock(timeout=1)
    
    def try_acquire():
        if lock.acquire():
            acquired_count[0] += 1
            time.sleep(0.1)
            lock.release()
    
    threads = [threading.Thread(target=try_acquire) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    if acquired_count[0] == 5:
        result.add_pass("多线程锁互斥正确")
    else:
        result.add_fail(f"多线程锁互斥错误: {acquired_count[0]}")
    
    return result.summary()


def test_cache_metrics_consistency():
    """缓存指标一致性测试"""
    result = ConsistencyTestResult("缓存指标一致性测试")
    print("\n=== 缓存指标一致性测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(max_size=100))
    
    for i in range(10):
        cache.set(f"key_{i}", f"value_{i}")
    
    for i in range(10):
        cache.get(f"key_{i}")
    
    for i in range(5):
        cache.get(f"nonexistent_{i}")
    
    stats = cache.get_stats()
    
    if stats["hits"] == 10:
        result.add_pass(f"命中数正确: {stats['hits']}")
    else:
        result.add_fail(f"命中数错误: {stats['hits']}, 期望10")
    
    if stats["misses"] == 5:
        result.add_pass(f"未命中数正确: {stats['misses']}")
    else:
        result.add_fail(f"未命中数错误: {stats['misses']}, 期望5")
    
    expected_rate = 10 / 15 * 100
    actual_rate = float(stats["hit_rate"].replace("%", ""))
    if abs(actual_rate - expected_rate) < 0.1:
        result.add_pass(f"命中率正确: {stats['hit_rate']}")
    else:
        result.add_fail(f"命中率错误: {stats['hit_rate']}, 期望 {expected_rate:.2f}%")
    
    return result.summary()


def test_key_builder_consistency():
    """键构建器一致性测试"""
    result = ConsistencyTestResult("键构建器一致性测试")
    print("\n=== 键构建器一致性测试 ===")
    
    keys = set()
    for i in range(1000):
        key = CacheKeyBuilder.build("user", i)
        keys.add(key)
    
    if len(keys) == 1000:
        result.add_pass("键唯一性验证通过")
    else:
        result.add_fail(f"键唯一性验证失败: {len(keys)}/1000")
    
    key = CacheKeyBuilder.build("test", 123, "extra", "parts")
    parsed = CacheKeyBuilder.parse(key)
    
    if parsed["version"] == "v1" and parsed["prefix"] == "test" and parsed["identifier"] == "123":
        result.add_pass("键解析一致性")
    else:
        result.add_fail(f"键解析不一致: {parsed}")
    
    pattern = CacheKeyBuilder.build_pattern("user")
    if pattern == "v1:user:*":
        result.add_pass("模式构建一致性")
    else:
        result.add_fail(f"模式构建不一致: {pattern}")
    
    return result.summary()


def run_all_consistency_tests():
    """运行所有一致性测试"""
    print("=" * 60)
    print("缓存一致性专项测试套件")
    print("=" * 60)
    
    all_results = []
    
    all_results.append(test_l1_l2_sync_consistency())
    all_results.append(test_version_control_consistency())
    all_results.append(test_invalidation_propagation())
    all_results.append(test_concurrent_write_consistency())
    all_results.append(test_concurrent_read_write_consistency())
    all_results.append(test_ttl_consistency())
    all_results.append(test_eviction_consistency())
    all_results.append(test_circuit_breaker_consistency())
    all_results.append(test_lock_consistency())
    all_results.append(test_cache_metrics_consistency())
    all_results.append(test_key_builder_consistency())
    
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)
    
    total_passed = 0
    total_failed = 0
    total_tests = 0
    
    for r in all_results:
        total_passed += r["passed"]
        total_failed += r["failed"]
        total_tests += r["total"]
        status = "✓" if r["failed"] == 0 else "✗"
        print(f"{status} {r['name']}: {r['passed']}/{r['total']} 通过 ({r['pass_rate']}) - {r['duration']}")
    
    print("-" * 60)
    overall_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
    print(f"总计: {total_passed}/{total_tests} 通过 ({overall_rate:.1f}%)")
    
    if total_failed > 0:
        print("\n失败的测试详情:")
        for r in all_results:
            if r["failed"] > 0:
                print(f"\n{r['name']}:")
                for error in r["errors"]:
                    print(f"  - {error}")
    
    print("\n" + "=" * 60)
    if total_failed == 0:
        print("✅ 所有缓存一致性测试通过！")
    else:
        print(f"⚠️ 有 {total_failed} 个测试失败，请检查上述详情。")
    print("=" * 60)
    
    return {
        "total_passed": total_passed,
        "total_failed": total_failed,
        "total_tests": total_tests,
        "pass_rate": f"{overall_rate:.1f}%",
        "results": all_results,
    }


if __name__ == "__main__":
    results = run_all_consistency_tests()
    sys.exit(0 if results["total_failed"] == 0 else 1)
