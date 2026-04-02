"""
测试快速降级策略
"""
import time
import sys
import os

from multilevel_cache.config import DegradationConfig, RedisConfig
from multilevel_cache.core import RedisCache


class MockRedisCache:
    """模拟Redis缓存用于测试"""
    
    def __init__(self):
        self.get_count = 0
        self.set_count = 0
        
    def get(self, key):
        self.get_count += 1
        raise ConnectionError("Mock Redis connection error")
    
    def set(self, key, value, ttl=None):
        self.set_count += 1
        raise ConnectionError("Mock Redis connection error")


def test_quick_degradation():
    """测试快速降级策略"""
    print("\n=== 测试快速降级策略 ===\n")
    
    config = RedisConfig(host="nonexistent", port=6379)
    degradation_config = DegradationConfig(
        failure_threshold=3,
        quick_degradation_window=10
    )
    
    cache = RedisCache(config, degradation_config)
    
    print(f"配置: failure_threshold={degradation_config.failure_threshold}, quick_degradation_window={degradation_config.quick_degradation_window}")
    print(f"初始状态: available={cache._available}, quick_degradation_mode={cache._quick_degradation_mode}")
    
    print("\n--- 首次触发降级 (需要达到 failure_threshold 次) ---")
    for i in range(3):
        result = cache.get(f"test_key_{i}")
        print(f"  第 {i+1} 次 get: result={result}, failure_count={cache._failure_count}, quick_degradation_mode={cache._quick_degradation_mode}")
    
    print(f"\n降级后状态: available={cache._available}, quick_degradation_mode={cache._quick_degradation_mode}")
    
    print("\n--- 后续操作 (应该快速降级，不再重试) ---")
    start_time = time.time()
    for i in range(5):
        result = cache.get(f"quick_test_{i}")
        elapsed = time.time() - start_time
        print(f"  第 {i+1} 次 get: result={result}, 耗时={elapsed*1000:.1f}ms")
    
    print(f"\n--- 等待降级窗口过期 ({degradation_config.quick_degradation_window}s) ---")
    print("等待中...")
    time.sleep(degradation_config.quick_degradation_window + 1)
    
    print(f"\n窗口过期后状态: quick_degradation_mode={cache._quick_degradation_mode}")
    
    result = cache.get("after_window")
    print(f"窗口过期后 get: result={result}, failure_count={cache._failure_count}, quick_degradation_mode={cache._quick_degradation_mode}")
    
    print("\n=== 测试完成 ===")


def test_degradation_status():
    """测试降级状态获取"""
    print("\n=== 测试降级状态获取 ===\n")
    
    config = RedisConfig(host="nonexistent", port=6379)
    degradation_config = DegradationConfig(
        failure_threshold=2,
        quick_degradation_window=5
    )
    
    cache = RedisCache(config, degradation_config)
    
    status = cache.get_degradation_status()
    print(f"初始状态: {status}")
    
    cache.get("test1")
    cache.get("test2")
    
    status = cache.get_degradation_status()
    print(f"触发降级后: {status}")
    
    print(f"is_quick_degradation 属性: {cache.is_quick_degradation}")
    
    print("\n=== 测试完成 ===\n")


if __name__ == "__main__":
    test_degradation_status()
    test_quick_degradation()
