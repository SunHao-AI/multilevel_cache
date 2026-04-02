"""
缓存一致性全面测试套件

测试覆盖：
1. 核心功能测试（读写删操作）
2. 多级缓存同步测试
3. 并发读写测试
4. 缓存失效和降级测试
5. 版本控制测试
6. 边界条件和异常场景
"""

import sys
import os
import time
import threading
import random
from concurrent.futures import ThreadPoolExecutor, as_completed

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


# ==================== 测试工具类 ====================

class TestResult:
    """测试结果"""
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


class ConsistencyChecker:
    """缓存一致性检查器"""
    
    @staticmethod
    def check_l1_l2_consistency(l1_cache, l2_cache, keys: list) -> dict:
        """检查L1和L2缓存一致性"""
        inconsistencies = []
        for key in keys:
            l1_value = l1_cache.get(key)
            l2_value = l2_cache.get(key) if l2_cache else None
            
            if l1_value != l2_value and l2_value is not None:
                inconsistencies.append({
                    "key": key,
                    "l1_value": l1_value,
                    "l2_value": l2_value,
                })
        
        return {
            "consistent": len(inconsistencies) == 0,
            "inconsistencies": inconsistencies,
            "checked_keys": len(keys),
        }
    
    @staticmethod
    def check_version_consistency(version_manager, entity_type: str, entity_id: int, expected_version: int) -> dict:
        """检查版本一致性"""
        actual_version = version_manager.get_version(entity_type, entity_id)
        return {
            "consistent": actual_version == expected_version,
            "expected": expected_version,
            "actual": actual_version,
        }


# ==================== 1. 核心功能测试 ====================

def test_core_operations():
    """核心功能测试：读写删操作"""
    result = TestResult("核心功能测试")
    print("\n=== 核心功能测试 ===")
    
    # 1.1 基本读写测试
    cache = MemoryCache(MemoryCacheConfig(max_size=100, default_ttl=60))
    
    cache.set("key1", "value1")
    if cache.get("key1") == "value1":
        result.add_pass("基本写入和读取")
    else:
        result.add_fail("基本写入和读取失败")
    
    # 1.2 覆盖写入测试
    cache.set("key1", "value1_updated")
    if cache.get("key1") == "value1_updated":
        result.add_pass("覆盖写入")
    else:
        result.add_fail("覆盖写入失败")
    
    # 1.3 删除测试
    cache.delete("key1")
    if cache.get("key1") is None:
        result.add_pass("删除操作")
    else:
        result.add_fail("删除操作失败")
    
    # 1.4 不存在的键测试
    if cache.get("nonexistent_key") is None:
        result.add_pass("获取不存在的键返回None")
    else:
        result.add_fail("获取不存在的键应返回None")
    
    # 1.5 删除不存在的键测试
    if cache.delete("nonexistent_key") == False:
        result.add_pass("删除不存在的键返回False")
    else:
        result.add_fail("删除不存在的键应返回False")
    
    # 1.6 TTL过期测试
    ttl_cache = MemoryCache(MemoryCacheConfig(max_size=100, default_ttl=1))
    ttl_cache.set("expire_key", "expire_value", ttl=1)
    time.sleep(1.5)
    if ttl_cache.get("expire_key") is None:
        result.add_pass("TTL过期自动删除")
    else:
        result.add_fail("TTL过期未自动删除")
    
    # 1.7 清空缓存测试
    cache.set("key2", "value2")
    cache.set("key3", "value3")
    cache.clear()
    if cache.get("key2") is None and cache.get("key3") is None:
        result.add_pass("清空缓存")
    else:
        result.add_fail("清空缓存失败")
    
    # 1.8 exists测试
    cache.set("exists_key", "value")
    if cache.exists("exists_key") == True and cache.exists("not_exists") == False:
        result.add_pass("exists检查")
    else:
        result.add_fail("exists检查失败")
    
    return result.summary()


# ==================== 2. 多级缓存同步测试 ====================

def test_multi_level_sync():
    """多级缓存同步测试"""
    result = TestResult("多级缓存同步测试")
    print("\n=== 多级缓存同步测试 ===")
    
    # 创建多级缓存（禁用L2以模拟纯内存测试）
    config = CacheConfig()
    config.degradation_config.enable_l2_fallback = False
    cache = MultiLevelCache(config)
    
    # 2.1 L1写入测试
    cache.set("sync_key1", "sync_value1")
    if cache.get("sync_key1") == "sync_value1":
        result.add_pass("L1写入和读取")
    else:
        result.add_fail("L1写入和读取失败")
    
    # 2.2 L1缓存命中测试
    cache.set("hit_key", "hit_value")
    cache.get("hit_key")  # 第一次获取
    stats = cache.get_stats()
    if stats["l1_stats"]["hits"] >= 1:
        result.add_pass("L1缓存命中统计")
    else:
        result.add_fail("L1缓存命中统计失败")
    
    # 2.3 L1未命中回源测试
    call_count = [0]
    def loader():
        call_count[0] += 1
        return "loaded_value"
    
    result1 = cache.get("new_key_1", loader=loader)
    result2 = cache.get("new_key_1", loader=loader)
    
    if result1 == "loaded_value" and call_count[0] == 1:
        result.add_pass("回源加载并缓存")
    else:
        result.add_fail(f"回源加载失败，call_count={call_count[0]}")
    
    # 2.4 多级缓存一致性检查
    cache.set("consistency_key", "consistency_value")
    checker = ConsistencyChecker()
    consistency = checker.check_l1_l2_consistency(
        cache.l1, cache.l2, ["consistency_key"]
    )
    if consistency["consistent"]:
        result.add_pass("L1缓存一致性")
    else:
        result.add_fail("L1缓存不一致")
    
    # 2.5 删除同步测试
    cache.set("delete_sync_key", "delete_value")
    cache.delete("delete_sync_key")
    if cache.get("delete_sync_key") is None:
        result.add_pass("删除后缓存一致性")
    else:
        result.add_fail("删除后缓存不一致")
    
    return result.summary()


# ==================== 3. 并发读写测试 ====================

def test_concurrent_operations():
    """并发读写测试"""
    result = TestResult("并发读写测试")
    print("\n=== 并发读写测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(thread_safe=True, max_size=10000))
    errors = []
    lock = threading.Lock()
    
    # 3.1 并发写入测试
    def concurrent_write(thread_id, count):
        try:
            for i in range(count):
                key = f"concurrent_key_{thread_id}_{i}"
                value = f"value_{thread_id}_{i}"
                cache.set(key, value)
        except Exception as e:
            with lock:
                errors.append(f"写入错误: {str(e)}")
    
    threads = []
    for i in range(10):
        t = threading.Thread(target=concurrent_write, args=(i, 100))
        threads.append(t)
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    if len(errors) == 0:
        result.add_pass("并发写入无错误")
    else:
        result.add_fail(f"并发写入有错误: {len(errors)}")
    
    # 3.2 并发读写混合测试
    read_errors = []
    write_errors = []
    
    def mixed_operations(thread_id, count):
        try:
            for i in range(count):
                key = f"mixed_key_{i % 50}"
                if random.random() > 0.5:
                    cache.set(key, f"value_{thread_id}_{i}")
                else:
                    cache.get(key)
        except Exception as e:
            with lock:
                if "read" in str(e).lower():
                    read_errors.append(str(e))
                else:
                    write_errors.append(str(e))
    
    threads = []
    for i in range(20):
        t = threading.Thread(target=mixed_operations, args=(i, 50))
        threads.append(t)
    
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    
    if len(read_errors) == 0 and len(write_errors) == 0:
        result.add_pass("并发读写混合无错误")
    else:
        result.add_fail(f"并发读写混合有错误: read={len(read_errors)}, write={len(write_errors)}")
    
    # 3.3 数据完整性检查
    cache.clear()
    for i in range(100):
        cache.set(f"integrity_key_{i}", f"integrity_value_{i}")
    
    integrity_errors = 0
    for i in range(100):
        key = f"integrity_key_{i}"
        expected = f"integrity_value_{i}"
        actual = cache.get(key)
        if actual != expected:
            integrity_errors += 1
    
    if integrity_errors == 0:
        result.add_pass("并发后数据完整性")
    else:
        result.add_fail(f"数据完整性错误: {integrity_errors}")
    
    return result.summary()


# ==================== 4. 缓存失效和降级测试 ====================

def test_cache_failure_and_degradation():
    """缓存失效和降级测试"""
    result = TestResult("缓存失效和降级测试")
    print("\n=== 缓存失效和降级测试 ===")
    
    # 4.1 TTL过期失效测试
    cache = MemoryCache(MemoryCacheConfig(max_size=100, default_ttl=1))
    cache.set("ttl_key", "ttl_value", ttl=1)
    
    if cache.get("ttl_key") == "ttl_value":
        result.add_pass("TTL设置成功")
    else:
        result.add_fail("TTL设置失败")
    
    time.sleep(1.5)
    
    if cache.get("ttl_key") is None:
        result.add_pass("TTL过期失效")
    else:
        result.add_fail("TTL过期未失效")
    
    # 4.2 容量淘汰测试
    small_cache = MemoryCache(MemoryCacheConfig(max_size=10, default_ttl=60))
    
    for i in range(15):
        small_cache.set(f"evict_key_{i}", f"value_{i}")
    
    stats = small_cache.get_stats()
    if stats["size"] <= 10:
        result.add_pass("容量淘汰生效")
    else:
        result.add_fail(f"容量淘汰未生效，size={stats['size']}")
    
    # 4.3 熔断器测试
    cb = CircuitBreaker(failure_threshold=3)
    
    if cb.is_available():
        result.add_pass("熔断器初始可用")
    else:
        result.add_fail("熔断器初始不可用")
    
    cb.record_failure()
    cb.record_failure()
    cb.record_failure()
    
    if not cb.is_available():
        result.add_pass("熔断器打开")
    else:
        result.add_fail("熔断器未打开")
    
    cb.reset()
    
    if cb.is_available():
        result.add_pass("熔断器重置后可用")
    else:
        result.add_fail("熔断器重置后不可用")
    
    # 4.4 本地锁测试
    lock = LocalLock(timeout=5)
    
    if lock.acquire():
        result.add_pass("本地锁获取成功")
    else:
        result.add_fail("本地锁获取失败")
    
    if lock.release():
        result.add_pass("本地锁释放成功")
    else:
        result.add_fail("本地锁释放失败")
    
    # 4.5 多级缓存禁用测试
    config = CacheConfig()
    config.degradation_config.enable_l2_fallback = False
    ml_cache = MultiLevelCache(config)
    
    ml_cache.disable()
    stats = ml_cache.get_stats()
    if not stats["enabled"]:
        result.add_pass("缓存禁用成功")
    else:
        result.add_fail("缓存禁用失败")
    
    ml_cache.enable()
    stats = ml_cache.get_stats()
    if stats["enabled"]:
        result.add_pass("缓存启用成功")
    else:
        result.add_fail("缓存启用失败")
    
    # 4.6 缓存穿透防护测试
    protection = CacheProtection()
    
    if protection.is_null_value("__NULL__"):
        result.add_pass("空值标记识别")
    else:
        result.add_fail("空值标记识别失败")
    
    # 4.7 TTL抖动测试
    ttl_values = [protection.add_jitter(100) for _ in range(10)]
    all_in_range = all(90 <= ttl <= 110 for ttl in ttl_values)
    
    if all_in_range:
        result.add_pass("TTL抖动范围正确")
    else:
        result.add_fail(f"TTL抖动范围错误: {ttl_values}")
    
    return result.summary()


# ==================== 5. 版本控制测试 ====================

def test_version_control():
    """版本控制测试"""
    result = TestResult("版本控制测试")
    print("\n=== 版本控制测试 ===")
    
    version_manager = CacheVersionManager()
    
    # 5.1 初始版本测试
    version = version_manager.get_version("task", 1)
    if version == 0:
        result.add_pass("初始版本为0")
    else:
        result.add_fail(f"初始版本应为0，实际为{version}")
    
    # 5.2 版本递增测试
    new_version = version_manager.increment_version("task", 1)
    if new_version == 1:
        result.add_pass("版本递增到1")
    else:
        result.add_fail(f"版本递增失败，实际为{new_version}")
    
    new_version = version_manager.increment_version("task", 1)
    if new_version == 2:
        result.add_pass("版本递增到2")
    else:
        result.add_fail(f"版本递增失败，实际为{new_version}")
    
    # 5.3 版本一致性检查
    checker = ConsistencyChecker()
    consistency = checker.check_version_consistency(version_manager, "task", 1, 2)
    if consistency["consistent"]:
        result.add_pass("版本一致性检查通过")
    else:
        result.add_fail(f"版本不一致: expected={consistency['expected']}, actual={consistency['actual']}")
    
    # 5.4 版本化缓存键测试
    versioned_key = version_manager.build_versioned_key("cache_key", "task", 1)
    if "v2" in versioned_key:
        result.add_pass("版本化键包含版本号")
    else:
        result.add_fail(f"版本化键不包含版本号: {versioned_key}")
    
    # 5.5 缓存有效性检查
    is_valid = version_manager.is_cache_valid("task", 1, 2)
    if is_valid:
        result.add_pass("缓存有效性检查通过")
    else:
        result.add_fail("缓存有效性检查失败")
    
    # 5.6 版本递增后缓存失效
    version_manager.increment_version("task", 1)  # 版本变为3
    is_valid = version_manager.is_cache_valid("task", 1, 2)  # 检查版本2
    if not is_valid:
        result.add_pass("版本递增后缓存失效")
    else:
        result.add_fail("版本递增后缓存应失效")
    
    # 5.7 版本统计测试
    stats = version_manager.get_stats()
    if stats["total_entities"] > 0:
        result.add_pass("版本统计正常")
    else:
        result.add_fail("版本统计异常")
    
    return result.summary()


# ==================== 6. 业务失效规则测试 ====================

def test_invalidation_rules():
    """业务失效规则测试"""
    result = TestResult("业务失效规则测试")
    print("\n=== 业务失效规则测试 ===")
    
    # 创建缓存和失效管理器
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
    
    # 6.1 任务缓存失效测试
    cache.set("v1:bt:123", "task_value")
    cache.set("v1:tl:all", "list_value")
    
    count = invalidation_manager.invalidate_task(123, notify_remote=False)
    if cache.get("v1:bt:123") is None:
        result.add_pass("任务缓存失效成功")
    else:
        result.add_fail("任务缓存失效失败")
    
    # 6.2 服务器缓存失效测试
    cache.set("v1:sn:456", "server_value")
    cache.set("v1:sc:456", "config_value")
    
    count = invalidation_manager.invalidate_server(456, notify_remote=False)
    if cache.get("v1:sn:456") is None:
        result.add_pass("服务器缓存失效成功")
    else:
        result.add_fail("服务器缓存失效失败")
    
    # 6.3 配置缓存失效测试
    cache.set("v1:cfg:789", "config_value")
    
    count = invalidation_manager.invalidate_config(789, notify_remote=False)
    if cache.get("v1:cfg:789") is None:
        result.add_pass("配置缓存失效成功")
    else:
        result.add_fail("配置缓存失效失败")
    
    # 6.4 规则键生成测试
    keys_info = rules.get_task_keys(100)
    if len(keys_info["keys"]) > 0:
        result.add_pass("任务规则键生成")
    else:
        result.add_fail("任务规则键生成失败")
    
    return result.summary()


# ==================== 7. 边界条件和异常场景测试 ====================

def test_edge_cases():
    """边界条件和异常场景测试"""
    result = TestResult("边界条件和异常场景测试")
    print("\n=== 边界条件和异常场景测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(max_size=100, default_ttl=60))
    
    # 7.1 空键测试
    try:
        cache.set("", "empty_key_value")
        if cache.get("") == "empty_key_value":
            result.add_pass("空键处理")
        else:
            result.add_fail("空键处理失败")
    except Exception as e:
        result.add_pass(f"空键抛出异常: {str(e)[:30]}")
    
    # 7.2 空值测试
    cache.set("null_value_key", None)
    if cache.get("null_value_key") is None:
        result.add_pass("空值处理")
    else:
        result.add_fail("空值处理失败")
    
    # 7.3 大键测试
    large_key = "k" * 1000
    cache.set(large_key, "large_key_value")
    if cache.get(large_key) == "large_key_value":
        result.add_pass("大键处理")
    else:
        result.add_fail("大键处理失败")
    
    # 7.4 大值测试
    large_value = "v" * 10000
    cache.set("large_value_key", large_value)
    if cache.get("large_value_key") == large_value:
        result.add_pass("大值处理")
    else:
        result.add_fail("大值处理失败")
    
    # 7.5 特殊字符键测试
    special_key = "key:with:special:chars:!@#$%"
    cache.set(special_key, "special_value")
    if cache.get(special_key) == "special_value":
        result.add_pass("特殊字符键处理")
    else:
        result.add_fail("特殊字符键处理失败")
    
    # 7.6 Unicode键测试
    unicode_key = "键_中文_日本語_한국어"
    cache.set(unicode_key, "unicode_value")
    if cache.get(unicode_key) == "unicode_value":
        result.add_pass("Unicode键处理")
    else:
        result.add_fail("Unicode键处理失败")
    
    # 7.7 复杂对象值测试
    complex_value = {
        "string": "value",
        "number": 123,
        "nested": {"a": 1, "b": 2},
        "list": [1, 2, 3],
    }
    cache.set("complex_key", complex_value)
    if cache.get("complex_key") == complex_value:
        result.add_pass("复杂对象值处理")
    else:
        result.add_fail("复杂对象值处理失败")
    
    # 7.8 零TTL测试
    cache.set("zero_ttl_key", "zero_ttl_value", ttl=0)
    if cache.get("zero_ttl_key") == "zero_ttl_value":
        result.add_pass("零TTL处理")
    else:
        result.add_fail("零TTL处理失败")
    
    return result.summary()


# ==================== 8. 性能测试 ====================

def test_performance():
    """性能测试"""
    result = TestResult("性能测试")
    print("\n=== 性能测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(max_size=100000, default_ttl=60))
    
    # 8.1 写入性能测试
    start_time = time.time()
    for i in range(10000):
        cache.set(f"perf_key_{i}", f"perf_value_{i}")
    write_duration = time.time() - start_time
    write_ops = 10000 / write_duration
    
    if write_ops > 10000:
        result.add_pass(f"写入性能: {write_ops:.0f} ops/s")
    else:
        result.add_fail(f"写入性能不足: {write_ops:.0f} ops/s")
    
    # 8.2 读取性能测试
    start_time = time.time()
    for i in range(10000):
        cache.get(f"perf_key_{i}")
    read_duration = time.time() - start_time
    read_ops = 10000 / read_duration
    
    if read_ops > 50000:
        result.add_pass(f"读取性能: {read_ops:.0f} ops/s")
    else:
        result.add_fail(f"读取性能不足: {read_ops:.0f} ops/s")
    
    # 8.3 延迟测试
    latencies = []
    for i in range(1000):
        start = time.time()
        cache.get(f"perf_key_{i}")
        latencies.append((time.time() - start) * 1000)  # ms
    
    avg_latency = sum(latencies) / len(latencies)
    p99_latency = sorted(latencies)[int(len(latencies) * 0.99)]
    
    if p99_latency < 1:  # < 1ms
        result.add_pass(f"P99延迟: {p99_latency:.3f}ms")
    else:
        result.add_fail(f"P99延迟过高: {p99_latency:.3f}ms")
    
    # 8.4 命中率测试
    stats = cache.get_stats()
    hit_rate = float(stats["hit_rate"].replace("%", ""))
    
    if hit_rate > 90:
        result.add_pass(f"命中率: {stats['hit_rate']}")
    else:
        result.add_fail(f"命中率不足: {stats['hit_rate']}")
    
    return result.summary()


# ==================== 9. 缓存键构建器测试 ====================

def test_cache_key_builder():
    """缓存键构建器测试"""
    result = TestResult("缓存键构建器测试")
    print("\n=== 缓存键构建器测试 ===")
    
    # 9.1 基本键构建
    key = CacheKeyBuilder.build("user", 123)
    if key == "v1:user:123":
        result.add_pass("基本键构建")
    else:
        result.add_fail(f"基本键构建失败: {key}")
    
    # 9.2 带额外部分的键构建
    key = CacheKeyBuilder.build("user", 123, "profile", "avatar")
    if key == "v1:user:123:profile:avatar":
        result.add_pass("带额外部分的键构建")
    else:
        result.add_fail(f"带额外部分的键构建失败: {key}")
    
    # 9.3 模式构建
    pattern = CacheKeyBuilder.build_pattern("user")
    if pattern == "v1:user:*":
        result.add_pass("模式构建")
    else:
        result.add_fail(f"模式构建失败: {pattern}")
    
    # 9.4 键解析
    parts = CacheKeyBuilder.parse("v1:user:123:profile")
    if parts["version"] == "v1" and parts["prefix"] == "user":
        result.add_pass("键解析")
    else:
        result.add_fail(f"键解析失败: {parts}")
    
    # 9.5 键一致性测试
    keys = [CacheKeyBuilder.build("task", i) for i in range(100)]
    unique_keys = set(keys)
    if len(unique_keys) == 100:
        result.add_pass("键唯一性")
    else:
        result.add_fail(f"键唯一性失败，重复数={100 - len(unique_keys)}")
    
    return result.summary()


# ==================== 10. 监控统计测试 ====================

def test_monitoring():
    """监控统计测试"""
    result = TestResult("监控统计测试")
    print("\n=== 监控统计测试 ===")
    
    monitor = CacheMonitor()
    
    # 10.1 命中记录
    monitor.record_hit("l1")
    monitor.record_hit("l1")
    monitor.record_hit("l2")
    
    if monitor.metrics.l1_hits == 2 and monitor.metrics.l2_hits == 1:
        result.add_pass("命中记录")
    else:
        result.add_fail("命中记录失败")
    
    # 10.2 未命中记录
    monitor.record_miss("l1")
    monitor.record_miss("l2")
    
    if monitor.metrics.l1_misses == 1 and monitor.metrics.l2_misses == 1:
        result.add_pass("未命中记录")
    else:
        result.add_fail("未命中记录失败")
    
    # 10.3 错误记录
    monitor.record_error("connection")
    monitor.record_error("timeout")
    
    if monitor.metrics.total_errors == 2:
        result.add_pass("错误记录")
    else:
        result.add_fail("错误记录失败")
    
    # 10.4 统计获取
    stats = monitor.get_stats()
    if "l1_hits" in stats and "l1_misses" in stats:
        result.add_pass("统计获取")
    else:
        result.add_fail("统计获取失败")
    
    # 10.5 重置
    monitor.reset()
    if monitor.metrics.l1_hits == 0 and monitor.metrics.l1_misses == 0:
        result.add_pass("统计重置")
    else:
        result.add_fail("统计重置失败")
    
    # 10.6 Prometheus导出测试
    prometheus_output = monitor.export_prometheus()
    if "cache_requests_total" in prometheus_output:
        result.add_pass("Prometheus导出")
    else:
        result.add_fail("Prometheus导出失败")
    
    return result.summary()


# ==================== 测试执行主函数 ====================

def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("多级缓存模块全面测试套件")
    print("重点验证缓存一致性")
    print("=" * 60)
    
    all_results = []
    
    # 执行所有测试
    all_results.append(test_core_operations())
    all_results.append(test_multi_level_sync())
    all_results.append(test_concurrent_operations())
    all_results.append(test_cache_failure_and_degradation())
    all_results.append(test_version_control())
    all_results.append(test_invalidation_rules())
    all_results.append(test_edge_cases())
    all_results.append(test_performance())
    all_results.append(test_cache_key_builder())
    all_results.append(test_monitoring())
    
    # 汇总结果
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
        print("✅ 所有测试通过！缓存一致性验证成功！")
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
    results = run_all_tests()
    sys.exit(0 if results["total_failed"] == 0 else 1)
