"""
并发场景测试套件

测试覆盖：
1. 高并发写入测试
2. 高并发读取测试
3. 并发读写混合测试
4. 并发删除测试
5. 并发失效测试
6. 压力测试
"""

import sys
import os
import time
import threading
import random
import queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass

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
from multilevel_cache.version import CacheVersionManager


@dataclass
class ConcurrentTestResult:
    """并发测试结果"""
    name: str
    passed: bool
    total_operations: int
    successful_operations: int
    failed_operations: int
    duration: float
    ops_per_second: float
    errors: List[str]
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "total_operations": self.total_operations,
            "successful_operations": self.successful_operations,
            "failed_operations": self.failed_operations,
            "duration": f"{self.duration:.3f}s",
            "ops_per_second": f"{self.ops_per_second:.0f}",
            "errors": self.errors[:10],
        }


class ConcurrentTestRunner:
    """并发测试运行器"""
    
    def __init__(self, thread_count: int = 20, operations_per_thread: int = 100):
        self.thread_count = thread_count
        self.operations_per_thread = operations_per_thread
        self.errors = []
        self.error_lock = threading.Lock()
    
    def add_error(self, error: str):
        with self.error_lock:
            self.errors.append(error)
    
    def run_test(self, name: str, test_func) -> ConcurrentTestResult:
        """运行并发测试"""
        self.errors = []
        start_time = time.time()
        
        successful = 0
        failed = 0
        
        with ThreadPoolExecutor(max_workers=self.thread_count) as executor:
            futures = []
            for i in range(self.thread_count):
                future = executor.submit(test_func, i)
                futures.append(future)
            
            for future in as_completed(futures):
                try:
                    result = future.result()
                    successful += result
                except Exception as e:
                    failed += 1
                    self.add_error(str(e))
        
        duration = time.time() - start_time
        total_ops = self.thread_count * self.operations_per_thread
        ops_per_sec = total_ops / duration if duration > 0 else 0
        
        return ConcurrentTestResult(
            name=name,
            passed=failed == 0 and len(self.errors) == 0,
            total_operations=total_ops,
            successful_operations=successful,
            failed_operations=failed,
            duration=duration,
            ops_per_second=ops_per_sec,
            errors=self.errors[:10],
        )


def test_high_concurrent_write():
    """高并发写入测试"""
    print("\n=== 高并发写入测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(thread_safe=True, max_size=100000))
    runner = ConcurrentTestRunner(thread_count=50, operations_per_thread=200)
    
    def write_operation(thread_id: int) -> int:
        count = 0
        for i in range(runner.operations_per_thread):
            key = f"write_key_{thread_id}_{i}"
            value = f"write_value_{thread_id}_{i}"
            try:
                cache.set(key, value)
                count += 1
            except Exception as e:
                runner.add_error(f"Write error: {e}")
        return count
    
    result = runner.run_test("高并发写入", write_operation)
    
    stats = cache.get_stats()
    print(f"  缓存大小: {stats['size']}")
    print(f"  操作数: {result.total_operations}")
    print(f"  成功率: {result.successful_operations}/{result.total_operations}")
    print(f"  吞吐量: {result.ops_per_second} ops/s")
    print(f"  耗时: {result.duration:.3f}s")
    
    if result.passed:
        print("  ✓ 高并发写入测试通过")
    else:
        print(f"  ✗ 高并发写入测试失败: {result.errors}")
    
    return result.to_dict()


def test_high_concurrent_read():
    """高并发读取测试"""
    print("\n=== 高并发读取测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(thread_safe=True, max_size=100000))
    
    for i in range(1000):
        cache.set(f"read_key_{i}", f"read_value_{i}")
    
    runner = ConcurrentTestRunner(thread_count=50, operations_per_thread=200)
    
    def read_operation(thread_id: int) -> int:
        count = 0
        for i in range(runner.operations_per_thread):
            key = f"read_key_{i % 1000}"
            try:
                value = cache.get(key)
                if value is not None:
                    count += 1
            except Exception as e:
                runner.add_error(f"Read error: {e}")
        return count
    
    result = runner.run_test("高并发读取", read_operation)
    
    stats = cache.get_stats()
    print(f"  命中数: {stats['hits']}")
    print(f"  未命中数: {stats['misses']}")
    print(f"  命中率: {stats['hit_rate']}")
    print(f"  吞吐量: {result.ops_per_second} ops/s")
    print(f"  耗时: {result.duration:.3f}s")
    
    if result.passed:
        print("  ✓ 高并发读取测试通过")
    else:
        print(f"  ✗ 高并发读取测试失败: {result.errors}")
    
    return result.to_dict()


def test_concurrent_read_write_mixed():
    """并发读写混合测试"""
    print("\n=== 并发读写混合测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(thread_safe=True, max_size=100000))
    
    for i in range(500):
        cache.set(f"mixed_key_{i}", f"mixed_value_{i}")
    
    runner = ConcurrentTestRunner(thread_count=30, operations_per_thread=100)
    read_count = [0]
    write_count = [0]
    count_lock = threading.Lock()
    
    def mixed_operation(thread_id: int) -> int:
        local_read = 0
        local_write = 0
        for i in range(runner.operations_per_thread):
            key = f"mixed_key_{i % 500}"
            try:
                if random.random() > 0.5:
                    value = cache.get(key)
                    local_read += 1
                else:
                    cache.set(key, f"updated_value_{thread_id}_{i}")
                    local_write += 1
            except Exception as e:
                runner.add_error(f"Mixed error: {e}")
        
        with count_lock:
            read_count[0] += local_read
            write_count[0] += local_write
        
        return local_read + local_write
    
    result = runner.run_test("并发读写混合", mixed_operation)
    
    print(f"  读取操作: {read_count[0]}")
    print(f"  写入操作: {write_count[0]}")
    print(f"  吞吐量: {result.ops_per_second} ops/s")
    print(f"  耗时: {result.duration:.3f}s")
    
    if result.passed:
        print("  ✓ 并发读写混合测试通过")
    else:
        print(f"  ✗ 并发读写混合测试失败: {result.errors}")
    
    return result.to_dict()


def test_concurrent_delete():
    """并发删除测试"""
    print("\n=== 并发删除测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(thread_safe=True, max_size=100000))
    
    for i in range(1000):
        cache.set(f"delete_key_{i}", f"delete_value_{i}")
    
    runner = ConcurrentTestRunner(thread_count=20, operations_per_thread=50)
    
    def delete_operation(thread_id: int) -> int:
        count = 0
        for i in range(runner.operations_per_thread):
            key = f"delete_key_{thread_id * 50 + i}"
            try:
                cache.delete(key)
                count += 1
            except Exception as e:
                runner.add_error(f"Delete error: {e}")
        return count
    
    result = runner.run_test("并发删除", delete_operation)
    
    print(f"  吞吐量: {result.ops_per_second} ops/s")
    print(f"  耗时: {result.duration:.3f}s")
    
    if result.passed:
        print("  ✓ 并发删除测试通过")
    else:
        print(f"  ✗ 并发删除测试失败: {result.errors}")
    
    return result.to_dict()


def test_concurrent_invalidation():
    """并发失效测试"""
    print("\n=== 并发失效测试 ===")
    
    config = CacheConfig()
    config.degradation_config.enable_l2_fallback = False
    cache = MultiLevelCache(config)
    version_manager = CacheVersionManager()
    
    for i in range(100):
        cache.set(f"invalidate_key_{i}", f"invalidate_value_{i}")
    
    runner = ConcurrentTestRunner(thread_count=10, operations_per_thread=20)
    version_increments = [0]
    version_lock = threading.Lock()
    
    def invalidate_operation(thread_id: int) -> int:
        count = 0
        for i in range(runner.operations_per_thread):
            entity_id = thread_id * 20 + i
            try:
                cache.delete(f"invalidate_key_{entity_id % 100}")
                version_manager.increment_version("test", entity_id)
                with version_lock:
                    version_increments[0] += 1
                count += 1
            except Exception as e:
                runner.add_error(f"Invalidate error: {e}")
        return count
    
    result = runner.run_test("并发失效", invalidate_operation)
    
    print(f"  版本递增次数: {version_increments[0]}")
    print(f"  吞吐量: {result.ops_per_second} ops/s")
    print(f"  耗时: {result.duration:.3f}s")
    
    if result.passed:
        print("  ✓ 并发失效测试通过")
    else:
        print(f"  ✗ 并发失效测试失败: {result.errors}")
    
    return result.to_dict()


def test_lock_contention():
    """锁竞争测试"""
    print("\n=== 锁竞争测试 ===")
    
    lock = LocalLock(timeout=10)
    counter = [0]
    counter_lock = threading.Lock()
    
    runner = ConcurrentTestRunner(thread_count=50, operations_per_thread=20)
    
    def lock_operation(thread_id: int) -> int:
        count = 0
        for i in range(runner.operations_per_thread):
            try:
                if lock.acquire():
                    with counter_lock:
                        counter[0] += 1
                    lock.release()
                    count += 1
                else:
                    runner.add_error(f"Lock acquire failed: thread {thread_id}")
            except Exception as e:
                runner.add_error(f"Lock error: {e}")
        return count
    
    result = runner.run_test("锁竞争", lock_operation)
    
    print(f"  成功获取锁次数: {counter[0]}")
    print(f"  吞吐量: {result.ops_per_second} ops/s")
    print(f"  耗时: {result.duration:.3f}s")
    
    if result.passed and counter[0] == result.total_operations:
        print("  ✓ 锁竞争测试通过")
    else:
        print(f"  ✗ 锁竞争测试失败: counter={counter[0]}, expected={result.total_operations}")
    
    return result.to_dict()


def test_stress_test():
    """压力测试"""
    print("\n=== 压力测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(thread_safe=True, max_size=500000))
    
    runner = ConcurrentTestRunner(thread_count=100, operations_per_thread=500)
    
    def stress_operation(thread_id: int) -> int:
        count = 0
        for i in range(runner.operations_per_thread):
            op_type = random.choice(["set", "get", "delete"])
            key = f"stress_key_{random.randint(0, 10000)}"
            
            try:
                if op_type == "set":
                    cache.set(key, f"stress_value_{thread_id}_{i}")
                elif op_type == "get":
                    cache.get(key)
                else:
                    cache.delete(key)
                count += 1
            except Exception as e:
                runner.add_error(f"Stress error: {e}")
        return count
    
    result = runner.run_test("压力测试", stress_operation)
    
    stats = cache.get_stats()
    print(f"  缓存大小: {stats['size']}")
    print(f"  总操作数: {result.total_operations}")
    print(f"  成功操作: {result.successful_operations}")
    print(f"  吞吐量: {result.ops_per_second} ops/s")
    print(f"  耗时: {result.duration:.3f}s")
    
    if result.passed:
        print("  ✓ 压力测试通过")
    else:
        print(f"  ✗ 压力测试失败: {result.errors}")
    
    return result.to_dict()


def test_data_integrity_under_concurrency():
    """并发下数据完整性测试"""
    print("\n=== 并发下数据完整性测试 ===")
    
    cache = MemoryCache(MemoryCacheConfig(thread_safe=True, max_size=10000))
    
    test_data = {f"integrity_key_{i}": f"integrity_value_{i}" for i in range(100)}
    
    for key, value in test_data.items():
        cache.set(key, value)
    
    integrity_errors = []
    error_lock = threading.Lock()
    
    runner = ConcurrentTestRunner(thread_count=20, operations_per_thread=50)
    
    def integrity_operation(thread_id: int) -> int:
        count = 0
        for i in range(runner.operations_per_thread):
            key = f"integrity_key_{i % 100}"
            try:
                value = cache.get(key)
                if value is not None:
                    expected = test_data.get(key)
                    if expected and value != expected and not value.startswith("updated_"):
                        with error_lock:
                            integrity_errors.append(f"Key {key}: expected {expected}, got {value}")
                count += 1
            except Exception as e:
                runner.add_error(f"Integrity error: {e}")
        return count
    
    result = runner.run_test("并发数据完整性", integrity_operation)
    
    print(f"  完整性错误数: {len(integrity_errors)}")
    print(f"  吞吐量: {result.ops_per_second} ops/s")
    print(f"  耗时: {result.duration:.3f}s")
    
    if result.passed and len(integrity_errors) == 0:
        print("  ✓ 并发数据完整性测试通过")
    else:
        print(f"  ✗ 并发数据完整性测试失败: {integrity_errors[:5]}")
    
    return result.to_dict()


def run_all_concurrent_tests():
    """运行所有并发测试"""
    print("=" * 60)
    print("并发场景测试套件")
    print("=" * 60)
    
    results = []
    
    results.append(test_high_concurrent_write())
    results.append(test_high_concurrent_read())
    results.append(test_concurrent_read_write_mixed())
    results.append(test_concurrent_delete())
    results.append(test_concurrent_invalidation())
    results.append(test_lock_contention())
    results.append(test_stress_test())
    results.append(test_data_integrity_under_concurrency())
    
    print("\n" + "=" * 60)
    print("并发测试结果汇总")
    print("=" * 60)
    
    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)
    
    for r in results:
        status = "✓" if r["passed"] else "✗"
        print(f"{status} {r['name']}: {r['successful_operations']}/{r['total_operations']} 操作, {r['ops_per_second']} ops/s")
    
    print("-" * 60)
    print(f"总计: {passed_count}/{total_count} 测试通过")
    
    print("\n" + "=" * 60)
    if passed_count == total_count:
        print("✅ 所有并发测试通过！")
    else:
        print(f"⚠️ 有 {total_count - passed_count} 个测试失败")
    print("=" * 60)
    
    return {
        "passed": passed_count,
        "failed": total_count - passed_count,
        "total": total_count,
        "results": results,
    }


if __name__ == "__main__":
    results = run_all_concurrent_tests()
    sys.exit(0 if results["failed"] == 0 else 1)
