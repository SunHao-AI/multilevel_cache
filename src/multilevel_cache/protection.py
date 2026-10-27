"""
缓存防护模块 - 实现缓存穿透、击穿、雪崩防护
"""

import hashlib
import logging
import threading
import time
import uuid as uuid_module
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProtectionConfig:
    """防护配置"""
    null_value_ttl: int = 60
    lock_timeout: int = 10
    jitter_min: float = 0.9
    jitter_max: float = 1.1
    bloom_filter_size: int = 100000
    bloom_filter_hashes: int = 7
    max_retry_attempts: int = 3
    retry_delay: float = 0.1


class CacheProtection:
    """
    缓存防护机制
    
    提供:
    - 缓存穿透防护 (空值缓存)
    - 缓存击穿防护 (分布式锁)
    - 缓存雪崩防护 (TTL抖动)
    """
    
    NULL_MARKER = "__NULL__"
    
    def __init__(self, config: ProtectionConfig = None):
        self.config = config or ProtectionConfig()
    
    def is_null_value(self, value: Any) -> bool:
        """检查是否为空值标记"""
        return value == self.NULL_MARKER
    
    def get_null_ttl(self) -> int:
        """获取空值缓存TTL"""
        return self.config.null_value_ttl
    
    def get_lock_timeout(self) -> int:
        """获取锁超时时间"""
        return self.config.lock_timeout
    
    def add_jitter(self, ttl: int) -> int:
        """添加TTL随机抖动"""
        import random
        if ttl <= 0:
            return ttl
        jitter = random.uniform(self.config.jitter_min, self.config.jitter_max)
        return int(ttl * jitter)


class DistributedLock:
    """
    分布式锁实现
    
    基于Redis SET NX EX实现
    """
    
    def __init__(
        self,
        redis_client,
        lock_key: str,
        timeout: int = 10,
        identifier: Optional[str] = None
    ):
        self.redis_client = redis_client
        self.lock_key = f"lock:{lock_key}"
        self.timeout = timeout
        self.identifier = identifier or self._generate_identifier()
        self._acquired = False
    
    def _generate_identifier(self) -> str:
        """生成锁标识（uuid4，避免跨进程 time+tid 相同导致误删他人锁）"""
        return uuid_module.uuid4().hex
    
    def acquire(self) -> bool:
        """获取锁"""
        try:
            # MLC-04: 必须走原生 redis 客户端做 SET NX EX。库内 RedisCache.set()
            # 签名为 (key, value, ttl)，不接收 nx —— 原实现 `set(..., nx=True)`
            # 每次必抛 TypeError 被吞掉，锁永远获取不到（或永远走降级）。
            client = getattr(self.redis_client, "client", None)
            if client is not None:
                result = client.set(
                    self.lock_key,
                    self.identifier,
                    ex=self.timeout,
                    nx=True,
                )
            else:
                # 兼容恰好实现了 (key, value, ttl, nx) 签名的注入实现
                result = self.redis_client.set(
                    self.lock_key,
                    self.identifier,
                    ttl=self.timeout,
                    nx=True
                )

            if result:
                self._acquired = True
                logger.debug(f"获取锁成功: {self.lock_key}")
                return True
            
            logger.debug(f"获取锁失败: {self.lock_key}")
            return False
            
        except Exception as e:
            logger.error(f"获取锁异常 [{self.lock_key}]: {str(e)}")
            return False
    
    def release(self) -> bool:
        """释放锁"""
        if not self._acquired:
            return False
        
        try:
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("del", KEYS[1])
            else
                return 0
            end
            """
            
            if hasattr(self.redis_client, 'client') and self.redis_client.client:
                result = self.redis_client.client.eval(
                    lua_script, 1, self.lock_key, self.identifier
                )
            else:
                result = False
            
            if result:
                self._acquired = False
                logger.debug(f"释放锁成功: {self.lock_key}")
                return True
            
            logger.warning(f"释放锁失败（锁已被其他进程持有）: {self.lock_key}")
            return False
            
        except Exception as e:
            logger.error(f"释放锁异常 [{self.lock_key}]: {str(e)}")
            return False
    
    def __enter__(self):
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
    
    def extend(self, additional_time: int = None) -> bool:
        """延长锁时间"""
        if not self._acquired:
            return False
        
        additional = additional_time or self.timeout
        
        try:
            lua_script = """
            if redis.call("get", KEYS[1]) == ARGV[1] then
                return redis.call("expire", KEYS[1], ARGV[2])
            else
                return 0
            end
            """
            
            if hasattr(self.redis_client, 'client') and self.redis_client.client:
                result = self.redis_client.client.eval(
                    lua_script, 1, self.lock_key, self.identifier, additional
                )
                return bool(result)
            
            return False
            
        except Exception as e:
            logger.error(f"延长锁时间异常 [{self.lock_key}]: {str(e)}")
            return False


class LocalLock:
    """
    本地锁实现
    
    用于单机环境或作为分布式锁的降级方案
    """
    
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self._lock = threading.Lock()
        self._acquired = False
        self._acquire_time = 0
    
    def acquire(self) -> bool:
        """获取锁"""
        acquired = self._lock.acquire(timeout=self.timeout)
        if acquired:
            self._acquired = True
            self._acquire_time = time.time()
        return acquired
    
    def release(self) -> bool:
        """释放锁"""
        if self._acquired:
            self._lock.release()
            self._acquired = False
            return True
        return False
    
    def __enter__(self):
        self.acquire()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()


class BloomFilter:
    """
    布隆过滤器实现
    
    基于Redis BitMap，用于防止缓存穿透
    """
    
    def __init__(
        self,
        redis_client,
        key: str = "bloom_filter",
        size: int = 100000,
        hash_count: int = 7
    ):
        self.redis_client = redis_client
        self.key = f"bf:{key}"
        self.size = size
        self.hash_count = hash_count
    
    def _hashes(self, item: str) -> List[int]:
        """生成多个哈希值"""
        result = []
        for i in range(self.hash_count):
            hash_val = hashlib.md5(f"{item}:{i}".encode()).hexdigest()
            result.append(int(hash_val, 16) % self.size)
        return result
    
    def add(self, item: str) -> None:
        """添加元素"""
        try:
            if hasattr(self.redis_client, 'client') and self.redis_client.client:
                with self.redis_client.client.get_connection() as conn:
                    for pos in self._hashes(item):
                        conn.setbit(self.key, pos, 1)
        except Exception as e:
            logger.error(f"布隆过滤器添加错误 [{item}]: {str(e)}")
    
    def exists(self, item: str) -> bool:
        """
        检查元素可能存在
        
        Returns:
            True: 元素可能存在（有误判率）
            False: 元素一定不存在
        """
        try:
            if hasattr(self.redis_client, 'client') and self.redis_client.client:
                with self.redis_client.client.get_connection() as conn:
                    for pos in self._hashes(item):
                        if not conn.getbit(self.key, pos):
                            return False
                    return True
        except Exception as e:
            logger.error(f"布隆过滤器检查错误 [{item}]: {str(e)}")
            return True
        
        return True
    
    def clear(self) -> None:
        """清空布隆过滤器"""
        try:
            self.redis_client.delete(self.key)
        except Exception as e:
            logger.error(f"布隆过滤器清空错误: {str(e)}")
    
    def add_many(self, items: List[str]) -> None:
        """批量添加"""
        for item in items:
            self.add(item)


class RateLimiter:
    """
    限流器实现
    
    基于Redis令牌桶算法
    """
    
    def __init__(
        self,
        redis_client,
        key: str,
        max_requests: int = 100,
        window_seconds: int = 60
    ):
        self.redis_client = redis_client
        self.key = f"rate_limit:{key}"
        self.max_requests = max_requests
        self.window_seconds = window_seconds
    
    # MLC-14: 原子滑窗——清理过期成员后先计数, 仅当未超限才写入本次请求。
    # 原 pipeline 先 zadd 后判定, 被拒绝的请求同样计入窗口,
    # 持续超限场景下计数单调膨胀、对合法请求逐渐"过紧"。
    # KEYS[1]=限流键 ARGV[1]=window_start ARGV[2]=max_requests
    # ARGV[3]=member(唯一, 由调用方带 uuid 避免同刻碰撞) ARGV[4]=score ARGV[5]=window TTL
    _LUA_SLIDING_WINDOW = """
    redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, ARGV[1])
    local count = redis.call('ZCARD', KEYS[1])
    if count < tonumber(ARGV[2]) then
        redis.call('ZADD', KEYS[1], ARGV[4], ARGV[3])
        redis.call('EXPIRE', KEYS[1], ARGV[5])
        return 1
    end
    return 0
    """

    def is_allowed(self, identifier: str = "default") -> bool:
        """检查是否允许请求（仅放行的请求计入窗口）"""
        try:
            current_time = time.time()
            window_start = current_time - self.window_seconds
            
            key = f"{self.key}:{identifier}"
            
            if hasattr(self.redis_client, 'client') and self.redis_client.client:
                # member 附加 uuid: 纯时间戳在时钟粒度粗的平台上会互相覆盖丢样本
                member = f"{current_time}:{uuid_module.uuid4().hex[:8]}"
                return bool(self.redis_client.client.eval(
                    self._LUA_SLIDING_WINDOW, 1, key,
                    window_start, self.max_requests,
                    member, current_time, self.window_seconds,
                ))
            
            return True
            
        except Exception as e:
            logger.error(f"限流器检查错误: {str(e)}")
            return True
    
    def get_remaining(self, identifier: str = "default") -> int:
        """获取剩余请求数"""
        try:
            current_time = time.time()
            window_start = current_time - self.window_seconds
            
            key = f"{self.key}:{identifier}"
            
            if hasattr(self.redis_client, 'client') and self.redis_client.client:
                # 注: 原实现走 client.get_connection() 拿到的是底层 Connection 对象
                # (无 zcard/zremrangebyscore 方法), 异常被下方 except 吞掉、
                # 恒回落 max_requests; redis.Redis 本身即命令客户端, 直接调用。
                self.redis_client.client.zremrangebyscore(key, 0, window_start)
                current_count = self.redis_client.client.zcard(key)
                return max(0, self.max_requests - current_count)
            
            return self.max_requests
            
        except Exception as e:
            logger.error(f"获取剩余请求数错误: {str(e)}")
            return self.max_requests


class CircuitBreaker:
    """
    熔断器实现
    
    用于防止级联故障
    """
    
    STATE_CLOSED = "closed"
    STATE_OPEN = "open"
    STATE_HALF_OPEN = "half_open"
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        half_open_requests: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_requests = half_open_requests
        
        self._state = self.STATE_CLOSED
        self._failure_count = 0
        self._last_failure_time = 0
        self._half_open_success_count = 0
        self._lock = threading.Lock()
    
    @property
    def state(self) -> str:
        """获取当前状态"""
        return self._state
    
    def is_available(self) -> bool:
        """检查是否可用"""
        with self._lock:
            if self._state == self.STATE_CLOSED:
                return True
            
            if self._state == self.STATE_OPEN:
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = self.STATE_HALF_OPEN
                    self._half_open_success_count = 0
                    logger.info("熔断器进入半开状态")
                    return True
                return False
            
            if self._state == self.STATE_HALF_OPEN:
                return True
        
        return False
    
    def record_success(self) -> None:
        """记录成功"""
        with self._lock:
            if self._state == self.STATE_HALF_OPEN:
                self._half_open_success_count += 1
                if self._half_open_success_count >= self.half_open_requests:
                    self._state = self.STATE_CLOSED
                    self._failure_count = 0
                    logger.info("熔断器恢复关闭状态")
            elif self._state == self.STATE_CLOSED:
                self._failure_count = 0
    
    def record_failure(self) -> None:
        """记录失败"""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            
            if self._state == self.STATE_HALF_OPEN:
                self._state = self.STATE_OPEN
                logger.warning("熔断器重新打开")
            elif self._state == self.STATE_CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._state = self.STATE_OPEN
                    logger.warning(
                        f"熔断器打开，失败次数: {self._failure_count}"
                    )
    
    def reset(self) -> None:
        """重置熔断器"""
        with self._lock:
            self._state = self.STATE_CLOSED
            self._failure_count = 0
            self._last_failure_time = 0
            self._half_open_success_count = 0
            logger.info("熔断器已重置")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "state": self._state,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout": self.recovery_timeout,
            "last_failure_time": self._last_failure_time,
        }
