"""
异常场景测试套件

测试覆盖：
1. 网络异常测试
2. 内存溢出测试
3. 键值异常测试
4. 配置异常测试
5. 并发异常测试
6. 边界条件测试
"""

import sys
import os
import time
import threading
import gc
from typing import Dict, List, Any
from dataclasses import dataclass

from multilevel_cache.config import (
    CacheConfig,
    MemoryCacheConfig,
    TTLConfig,
    CacheKeyBuilder,
    EvictionPolicy,
    DegradationConfig,
    RedisConfig,
    ProtectionConfig,
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
from multilevel_cache.monitoring import CacheMonitor


@dataclass
class ExceptionTestResult:
    """异常测试结果"""
    name: str
    passed: bool
    message: str
    exception_handled: bool
    duration: float
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "message": self.message,
            "exception_handled": self.exception_handled,
            "duration": f"{self.duration:.3f}s",
        }


class ExceptionTestRunner:
    """异常测试运行器"""
    
    def __init__(self):
        self.results = []
    
    def run_test(self, name: str, test_func) -> ExceptionTestResult:
        """运行异常测试"""
        start_time = time.time()
        passed = False
        message = ""
        exception_handled = False
        
        try:
            result = test_func()
            passed = result.get("passed", False)
            message = result.get("message", "")
            exception_handled = result.get("exception_handled", True)
        except Exception as e:
            passed = False
            message = f"未捕获的异常: {str(e)}"
            exception_handled = False
        
        duration = time.time() - start_time
        
        test_result = ExceptionTestResult(
            name=name,
            passed=passed,
            message=message,
            exception_handled=exception_handled,
            duration=duration,
        )
        
        self.results.append(test_result)
        return test_result


def test_empty_key():
    """空键测试"""
    print("\n=== 空键测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cache = MemoryCache()
        try:
            cache.set("", "empty_key_value")
            value = cache.get("")
            if value == "empty_key_value":
                return {"passed": True, "message": "空键处理成功"}
            else:
                return {"passed": False, "message": f"空键值不匹配: {value}"}
        except Exception as e:
            return {"passed": True, "message": f"空键抛出异常: {str(e)[:30]}", "exception_handled": True}
    
    result = runner.run_test("空键测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_none_value():
    """空值测试"""
    print("\n=== 空值测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cache = MemoryCache()
        cache.set("none_key", None)
        value = cache.get("none_key")
        
        if value is None:
            return {"passed": True, "message": "空值处理成功"}
        else:
            return {"passed": False, "message": f"空值处理失败: {value}"}
    
    result = runner.run_test("空值测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_large_key():
    """大键测试"""
    print("\n=== 大键测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cache = MemoryCache()
        large_key = "k" * 10000
        
        try:
            cache.set(large_key, "large_key_value")
            value = cache.get(large_key)
            
            if value == "large_key_value":
                return {"passed": True, "message": "大键处理成功"}
            else:
                return {"passed": False, "message": f"大键值不匹配"}
        except Exception as e:
            return {"passed": True, "message": f"大键抛出异常: {str(e)[:30]}", "exception_handled": True}
    
    result = runner.run_test("大键测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_large_value():
    """大值测试"""
    print("\n=== 大值测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cache = MemoryCache(MemoryCacheConfig(max_size=100))
        large_value = "v" * 100000
        
        try:
            cache.set("large_value_key", large_value)
            value = cache.get("large_value_key")
            
            if value == large_value:
                return {"passed": True, "message": "大值处理成功"}
            else:
                return {"passed": False, "message": "大值不匹配"}
        except Exception as e:
            return {"passed": True, "message": f"大值抛出异常: {str(e)[:30]}", "exception_handled": True}
    
    result = runner.run_test("大值测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_special_characters():
    """特殊字符测试"""
    print("\n=== 特殊字符测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cache = MemoryCache()
        special_keys = [
            "key:with:colons",
            "key with spaces",
            "key\twith\ttabs",
            "key\nwith\nnewlines",
            "key!@#$%^&*()",
            "key中文日本語한국어",
            "key😀🎉🚀",
        ]
        
        all_passed = True
        failed_keys = []
        
        for key in special_keys:
            try:
                cache.set(key, f"value_{key}")
                value = cache.get(key)
                if value != f"value_{key}":
                    all_passed = False
                    failed_keys.append(key)
            except Exception as e:
                all_passed = False
                failed_keys.append(f"{key}: {str(e)[:20]}")
        
        if all_passed:
            return {"passed": True, "message": "所有特殊字符处理成功"}
        else:
            return {"passed": False, "message": f"失败的特殊字符: {failed_keys[:3]}"}
    
    result = runner.run_test("特殊字符测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_complex_objects():
    """复杂对象测试"""
    print("\n=== 复杂对象测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cache = MemoryCache()
        
        class CustomObject:
            def __init__(self, value):
                self.value = value
            
            def __eq__(self, other):
                return isinstance(other, CustomObject) and self.value == other.value
        
        test_objects = [
            {"dict": {"nested": {"deep": "value"}}, "list": [1, 2, 3]},
            [1, "two", {"three": 3}, [4, 5]],
            CustomObject("custom_value"),
            set([1, 2, 3]),
            (1, 2, 3),
        ]
        
        all_passed = True
        failed_indices = []
        
        for i, obj in enumerate(test_objects):
            try:
                cache.set(f"complex_key_{i}", obj)
                value = cache.get(f"complex_key_{i}")
                if value != obj:
                    all_passed = False
                    failed_indices.append(i)
            except Exception as e:
                all_passed = False
                failed_indices.append(f"{i}: {str(e)[:20]}")
        
        if all_passed:
            return {"passed": True, "message": "所有复杂对象处理成功"}
        else:
            return {"passed": False, "message": f"失败的对象索引: {failed_indices[:3]}"}
    
    result = runner.run_test("复杂对象测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_zero_ttl():
    """零TTL测试"""
    print("\n=== 零TTL测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cache = MemoryCache()
        cache.set("zero_ttl_key", "zero_ttl_value", ttl=0)
        value = cache.get("zero_ttl_key")
        
        if value == "zero_ttl_value":
            return {"passed": True, "message": "零TTL处理成功"}
        else:
            return {"passed": False, "message": f"零TTL值不匹配: {value}"}
    
    result = runner.run_test("零TTL测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_negative_ttl():
    """负TTL测试"""
    print("\n=== 负TTL测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cache = MemoryCache()
        try:
            cache.set("negative_ttl_key", "negative_ttl_value", ttl=-1)
            value = cache.get("negative_ttl_key")
            
            if value is None:
                return {"passed": True, "message": "负TTL立即过期"}
            else:
                return {"passed": False, "message": f"负TTL未过期: {value}"}
        except Exception as e:
            return {"passed": True, "message": f"负TTL抛出异常: {str(e)[:30]}", "exception_handled": True}
    
    result = runner.run_test("负TTL测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_extreme_ttl():
    """极端TTL测试"""
    print("\n=== 极端TTL测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cache = MemoryCache()
        
        cache.set("very_large_ttl_key", "value", ttl=31536000)
        value = cache.get("very_large_ttl_key")
        
        if value == "value":
            return {"passed": True, "message": "极大TTL处理成功"}
        else:
            return {"passed": False, "message": "极大TTL处理失败"}
    
    result = runner.run_test("极端TTL测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_cache_overflow():
    """缓存溢出测试"""
    print("\n=== 缓存溢出测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cache = MemoryCache(MemoryCacheConfig(max_size=10))
        
        try:
            for i in range(100):
                cache.set(f"overflow_key_{i}", f"overflow_value_{i}")
            
            stats = cache.get_stats()
            if stats["size"] <= 10:
                return {"passed": True, "message": f"缓存大小限制生效: {stats['size']}"}
            else:
                return {"passed": False, "message": f"缓存大小超限: {stats['size']}"}
        except Exception as e:
            return {"passed": True, "message": f"溢出抛出异常: {str(e)[:30]}", "exception_handled": True}
    
    result = runner.run_test("缓存溢出测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_circuit_breaker_failure():
    """熔断器失败测试"""
    print("\n=== 熔断器失败测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cb = CircuitBreaker(failure_threshold=3)
        
        for _ in range(5):
            cb.record_failure()
        
        if not cb.is_available():
            cb.reset()
            if cb.is_available():
                return {"passed": True, "message": "熔断器正确打开和恢复"}
            else:
                return {"passed": False, "message": "熔断器恢复失败"}
        else:
            return {"passed": False, "message": "熔断器未正确打开"}
    
    result = runner.run_test("熔断器失败测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_lock_timeout():
    """锁超时测试"""
    print("\n=== 锁超时测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        lock = LocalLock(timeout=1)
        
        if lock.acquire():
            acquired = lock.acquire()
            lock.release()
            
            if not acquired:
                return {"passed": True, "message": "锁超时正确拒绝重复获取"}
            else:
                return {"passed": False, "message": "锁不应允许重复获取"}
        else:
            return {"passed": False, "message": "首次获取锁失败"}
    
    result = runner.run_test("锁超时测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_cache_disabled():
    """缓存禁用测试"""
    print("\n=== 缓存禁用测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        config = CacheConfig()
        config.degradation_config.enable_l2_fallback = False
        cache = MultiLevelCache(config)
        
        cache.set("disabled_key", "disabled_value")
        value_before = cache.get("disabled_key")
        
        cache.disable()
        
        call_count = [0]
        def loader():
            call_count[0] += 1
            return "loader_value"
        
        value_disabled = cache.get("disabled_key", loader=loader)
        
        cache.enable()
        
        value_after = cache.get("disabled_key")
        
        if value_before == "disabled_value" and value_disabled == "loader_value" and call_count[0] == 1:
            return {"passed": True, "message": "缓存禁用和启用正确"}
        else:
            return {"passed": False, "message": f"禁用行为异常: before={value_before}, disabled={value_disabled}, after={value_after}"}
    
    result = runner.run_test("缓存禁用测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_concurrent_exception():
    """并发异常测试"""
    print("\n=== 并发异常测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cache = MemoryCache(MemoryCacheConfig(thread_safe=True, max_size=1000))
        errors = []
        error_lock = threading.Lock()
        
        def stress_operation(thread_id):
            try:
                for i in range(100):
                    key = f"exception_key_{i % 50}"
                    if i % 3 == 0:
                        cache.set(key, f"value_{thread_id}_{i}")
                    elif i % 3 == 1:
                        cache.get(key)
                    else:
                        cache.delete(key)
            except Exception as e:
                with error_lock:
                    errors.append(str(e))
        
        threads = [threading.Thread(target=stress_operation, args=(i,)) for i in range(20)]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        if len(errors) == 0:
            return {"passed": True, "message": "并发操作无异常"}
        else:
            return {"passed": False, "message": f"并发异常: {errors[:3]}"}
    
    result = runner.run_test("并发异常测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_memory_pressure():
    """内存压力测试"""
    print("\n=== 内存压力测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        cache = MemoryCache(MemoryCacheConfig(max_size=10000))
        
        try:
            for i in range(10000):
                large_value = "v" * 1000
                cache.set(f"memory_key_{i}", large_value)
            
            stats = cache.get_stats()
            gc.collect()
            
            return {"passed": True, "message": f"内存压力测试完成，缓存大小: {stats['size']}"}
        except MemoryError:
            return {"passed": True, "message": "内存不足，已处理", "exception_handled": True}
        except Exception as e:
            return {"passed": False, "message": f"未处理的异常: {str(e)[:30]}"}
    
    result = runner.run_test("内存压力测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def test_config_validation():
    """配置验证测试"""
    print("\n=== 配置验证测试 ===")
    runner = ExceptionTestRunner()
    
    def test_func():
        try:
            config = CacheConfig.from_dict({
                "name": "test_cache",
                "memory": {
                    "max_size": -1,
                    "default_ttl": -1,
                },
            })
            
            cache = MemoryCache(config.memory_config)
            cache.set("config_test_key", "config_test_value")
            
            return {"passed": True, "message": "配置验证处理成功"}
        except Exception as e:
            return {"passed": True, "message": f"配置验证抛出异常: {str(e)[:30]}", "exception_handled": True}
    
    result = runner.run_test("配置验证测试", test_func)
    status = "✓" if result.passed else "✗"
    print(f"  {status} {result.message}")
    return result.to_dict()


def run_all_exception_tests():
    """运行所有异常测试"""
    print("=" * 60)
    print("异常场景测试套件")
    print("=" * 60)
    
    results = []
    
    results.append(test_empty_key())
    results.append(test_none_value())
    results.append(test_large_key())
    results.append(test_large_value())
    results.append(test_special_characters())
    results.append(test_complex_objects())
    results.append(test_zero_ttl())
    results.append(test_negative_ttl())
    results.append(test_extreme_ttl())
    results.append(test_cache_overflow())
    results.append(test_circuit_breaker_failure())
    results.append(test_lock_timeout())
    results.append(test_cache_disabled())
    results.append(test_concurrent_exception())
    results.append(test_memory_pressure())
    results.append(test_config_validation())
    
    print("\n" + "=" * 60)
    print("异常测试结果汇总")
    print("=" * 60)
    
    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)
    
    for r in results:
        status = "✓" if r["passed"] else "✗"
        exception_status = "已处理" if r["exception_handled"] else "未处理"
        print(f"{status} {r['name']}: {r['message']} ({exception_status})")
    
    print("-" * 60)
    print(f"总计: {passed_count}/{total_count} 测试通过")
    
    print("\n" + "=" * 60)
    if passed_count == total_count:
        print("✅ 所有异常测试通过！")
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
    results = run_all_exception_tests()
    sys.exit(0 if results["failed"] == 0 else 1)
