"""
核心缓存模块 - 定义缓存后端抽象和具体实现
"""

import fnmatch
import hashlib
import json
import logging
import pickle
import threading
import time
from abc import ABC, abstractmethod
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union

from multilevel_cache.config import (
    CacheConfig,
    MemoryCacheConfig,
    RedisConfig,
    TTLConfig,
    EvictionPolicy,
)

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """缓存条目"""
    value: Any
    expire_at: float
    created_at: float
    access_count: int = 0
    last_access: float = 0.0


class CacheBackend(ABC):
    """缓存后端抽象基类"""
    
    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        pass
    
    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存值"""
        pass
    
    @abstractmethod
    def delete(self, key: str) -> bool:
        """删除缓存"""
        pass
    
    @abstractmethod
    def exists(self, key: str) -> bool:
        """检查键是否存在"""
        pass
    
    @abstractmethod
    def clear(self) -> None:
        """清空缓存"""
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        pass


class MemoryCache(CacheBackend):
    """
    内存缓存实现
    
    特性:
    - 支持LRU/LFU/FIFO淘汰策略
    - 线程安全
    - TTL过期管理
    - 访问统计
    """
    
    def __init__(self, config: MemoryCacheConfig = None):
        self.config = config or MemoryCacheConfig()
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock() if self.config.thread_safe else None
        
        self._hits = 0
        self._misses = 0
        self._evictions = 0
    
    def _now(self) -> float:
        return time.time()
    
    def _is_expired(self, entry: CacheEntry) -> bool:
        return self._now() > entry.expire_at
    
    def _evict(self) -> None:
        """执行淘汰策略"""
        if not self._cache:
            return
        
        if self.config.eviction_policy == EvictionPolicy.LRU:
            self._evict_lru()
        elif self.config.eviction_policy == EvictionPolicy.LFU:
            self._evict_lfu()
        elif self.config.eviction_policy == EvictionPolicy.FIFO:
            self._evict_fifo()
        else:
            self._evict_ttl()
    
    def _evict_lru(self) -> None:
        """LRU淘汰"""
        oldest_key = min(
            self._cache.keys(),
            key=lambda k: self._cache[k].last_access
        )
        del self._cache[oldest_key]
        self._evictions += 1
    
    def _evict_lfu(self) -> None:
        """LFU淘汰"""
        least_key = min(
            self._cache.keys(),
            key=lambda k: self._cache[k].access_count
        )
        del self._cache[least_key]
        self._evictions += 1
    
    def _evict_fifo(self) -> None:
        """FIFO淘汰"""
        oldest_key = next(iter(self._cache))
        del self._cache[oldest_key]
        self._evictions += 1
    
    def _evict_ttl(self) -> None:
        """TTL淘汰"""
        now = self._now()
        expired_keys = [
            k for k, v in self._cache.items()
            if v.expire_at < now
        ]
        for key in expired_keys:
            del self._cache[key]
            self._evictions += 1
        
        if not expired_keys and self._cache:
            self._evict_lru()
    
    def _cleanup_expired(self) -> int:
        """清理过期条目"""
        now = self._now()
        expired_keys = [
            k for k, v in self._cache.items()
            if v.expire_at < now
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)
    
    def _with_lock(self, func: Callable) -> Any:
        """带锁执行"""
        if self._lock:
            with self._lock:
                return func()
        return func()
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        def _get():
            if key not in self._cache:
                self._misses += 1
                return None
            
            entry = self._cache[key]
            
            if self._is_expired(entry):
                del self._cache[key]
                self._misses += 1
                return None
            
            entry.access_count += 1
            entry.last_access = self._now()
            self._hits += 1
            
            if self.config.eviction_policy == EvictionPolicy.LRU:
                self._cache.move_to_end(key)
            
            return entry.value
        
        return self._with_lock(_get)
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存值"""
        def _set():
            actual_ttl = ttl if ttl is not None else self.config.default_ttl
            now = self._now()
            
            if len(self._cache) >= self.config.max_size and key not in self._cache:
                self._cleanup_expired()
                if len(self._cache) >= self.config.max_size:
                    self._evict()
            
            self._cache[key] = CacheEntry(
                value=value,
                expire_at=now + actual_ttl,
                created_at=now,
                access_count=1,
                last_access=now,
            )
            
            return True
        
        return self._with_lock(_set)
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        def _delete():
            if key in self._cache:
                del self._cache[key]
                return True
            return False
        
        return self._with_lock(_delete)
    
    def exists(self, key: str) -> bool:
        """检查键是否存在"""
        def _exists():
            if key not in self._cache:
                return False
            entry = self._cache[key]
            if self._is_expired(entry):
                del self._cache[key]
                return False
            return True
        
        return self._with_lock(_exists)
    
    def clear(self) -> None:
        """清空缓存"""
        def _clear():
            self._cache.clear()
            self._hits = 0
            self._misses = 0
            self._evictions = 0
        
        self._with_lock(_clear)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        total = self._hits + self._misses
        hit_rate = (self._hits / total * 100) if total > 0 else 0.0
        
        return {
            "size": len(self._cache),
            "max_size": self.config.max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": f"{hit_rate:.2f}%",
            "evictions": self._evictions,
            "eviction_policy": self.config.eviction_policy.value,
        }
    
    def keys(self) -> List[str]:
        """获取所有键"""
        return list(self._cache.keys())
    
    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """批量获取"""
        return {k: self.get(k) for k in keys}
    
    def set_many(self, mapping: Dict[str, Any], ttl: Optional[int] = None) -> int:
        """批量设置"""
        count = 0
        for k, v in mapping.items():
            if self.set(k, v, ttl):
                count += 1
        return count
    
    def delete_many(self, keys: List[str]) -> int:
        """批量删除"""
        count = 0
        for k in keys:
            if self.delete(k):
                count += 1
        return count


class RedisCache(CacheBackend):
    """
    Redis缓存实现
    
    特性:
    - 连接池管理
    - 序列化/反序列化
    - 分布式支持
    - 故障降级
    """
    
    def __init__(self, config: RedisConfig = None, degradation_config: 'DegradationConfig' = None):
        self.config = config or RedisConfig()
        self.degradation_config = degradation_config or DegradationConfig()
        self._client = None
        self._pool = None
        self._available = True
        self._failure_count = 0
        
        self._hits = 0
        self._misses = 0
        self._errors = 0
        
        self._quick_degradation_mode = False
        self._degradation_start_time = 0.0
        self._last_failure_time = 0.0
        self._consecutive_degradations = 0
        self._probe_check_done = False
        
        self._init_pool()
    
    def _init_pool(self) -> None:
        """初始化连接池"""
        try:
            import redis
            from redis.connection import ConnectionPool
            
            kwargs = {
                "host": self.config.host,
                "port": self.config.port,
                "db": self.config.db,
                "socket_timeout": self.config.socket_timeout,
                "socket_connect_timeout": self.config.socket_connect_timeout,
                "max_connections": self.config.max_connections,
                "decode_responses": self.config.decode_responses,
            }
            
            if self.config.password:
                kwargs["password"] = self.config.password
            if self.config.ssl:
                kwargs["ssl"] = True
            
            self._pool = ConnectionPool(**kwargs)
            self._client = redis.Redis(connection_pool=self._pool)
            
            logger.info(
                f"Redis连接池初始化成功: {self.config.host}:{self.config.port}/{self.config.db}"
            )
        except ImportError:
            logger.warning("redis库未安装，Redis缓存不可用")
            self._available = False
        except Exception as e:
            logger.error(f"Redis连接池初始化失败: {str(e)}")
            self._available = False
    
    @property
    def client(self):
        """获取Redis客户端"""
        return self._client
    
    @property
    def is_available(self) -> bool:
        """检查Redis是否可用"""
        return self._available
    
    @property
    def is_quick_degradation(self) -> bool:
        """检查是否处于快速降级模式"""
        if not self._quick_degradation_mode:
            return False
        elapsed = time.time() - self._degradation_start_time
        if elapsed > self.degradation_config.quick_degradation_window:
            return False
        return True
    
    def get_degradation_status(self) -> Dict[str, Any]:
        """获取降级状态详情"""
        return {
            "quick_degradation_mode": self._quick_degradation_mode,
            "failure_count": self._failure_count,
            "failure_threshold": self.degradation_config.failure_threshold,
            "degradation_window": self.degradation_config.quick_degradation_window,
            "remaining_time": max(
                0, 
                self.degradation_config.quick_degradation_window - (time.time() - self._degradation_start_time)
            ) if self._quick_degradation_mode else 0,
        }
    
    def _serialize(self, value: Any) -> Union[str, bytes]:
        """序列化值"""
        if isinstance(value, (str, int, float, bool)):
            return str(value)
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return pickle.dumps(value)
    
    def _deserialize(self, value: Any) -> Any:
        """反序列化值"""
        if value is None:
            return None
        if isinstance(value, bytes):
            try:
                return pickle.loads(value)
            except Exception:
                value = value.decode('utf-8')
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        return value
    
    def _handle_error(self, error: Exception, operation: str) -> bool:
        """
        处理错误并实现快速降级策略
        
        降级策略：
        - 首次触发：执行最多 failure_threshold 次查询尝试后进入降级状态
        - 后续操作：基于上一次降级结果实现快速降级，避免重复多次查询
        - 降级窗口：在 quick_degradation_window 秒内保持快速降级状态
        - 恢复检查：窗口过期后恢复正常的失败计数和检查机制
        """
        self._errors += 1
        current_time = time.time()
        
        logger.error(f"Redis {operation} 错误: {str(error)}")
        
        if self._quick_degradation_mode:
            window_elapsed = current_time - self._degradation_start_time
            
            if window_elapsed > self.degradation_config.quick_degradation_window:
                self._quick_degradation_mode = False
                self._failure_count = 0
                self._available = True
                logger.info(f"Redis快速降级窗口过期，恢复正常检查模式，窗口时间: {window_elapsed:.1f}s")
                return True
            
            logger.debug(f"Redis处于快速降级模式，跳过重试，剩余时间: {self.degradation_config.quick_degradation_window - window_elapsed:.1f}s")
            return False
        
        self._failure_count += 1
        self._last_failure_time = current_time
        
        if self._failure_count >= self.degradation_config.failure_threshold:
            self._quick_degradation_mode = True
            self._degradation_start_time = current_time
            self._available = False
            logger.warning(
                f"Redis连续失败{self._failure_count}次，启用快速降级模式，"
                f"窗口时间: {self.degradation_config.quick_degradation_window}s"
            )
            return False
        
        logger.info(f"Redis失败计数: {self._failure_count}/{self.degradation_config.failure_threshold}")
        return True
    
    def _check_availability(self) -> bool:
        """检查可用性"""
        if not self._client:
            return False
        
        try:
            if self._client.ping():
                self._available = True
                self._failure_count = 0
                return True
        except Exception:
            pass
        
        return False
    
    def _probe_redis(self, timeout: float = 1.0) -> bool:
        """
        轻量级探测Redis是否可用
        
        使用短超时进行快速探测，避免长时间等待
        
        :param timeout: 探测超时时间（秒），默认1秒
        :return: True表示Redis可用，False表示不可用
        """
        if not self._client:
            return False
        
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((self.config.host, self.config.port))
            sock.close()
            logger.info("Redis探测成功，服务已恢复")
            return True
        except Exception as e:
            logger.debug(f"Redis探测失败: {str(e)}")
        
        return False
    
    @contextmanager
    def _get_connection(self):
        """获取连接上下文"""
        try:
            yield self._client
        except Exception as e:
            self._handle_error(e, "connection")
            raise
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            if elapsed <= self.degradation_config.quick_degradation_window:
                self._misses += 1
                logger.debug(f"Redis快速降级模式，跳过GET操作，剩余时间: {self.degradation_config.quick_degradation_window - elapsed:.1f}s")
                return None
            else:
                logger.info(f"Redis快速降级窗口过期，执行探测检查")
                if not self._probe_redis():
                    logger.warning(f"Redis探测检查失败，继续快速降级模式")
                    self._quick_degradation_mode = True
                    self._degradation_start_time = time.time()
                    self._consecutive_degradations += 1
                    logger.warning(
                        f"Redis连续降级{self._consecutive_degradations}次，延长快速降级窗口至 "
                        f"{self.degradation_config.quick_degradation_window}s"
                    )
                    return None
                else:
                    self._quick_degradation_mode = False
                    self._failure_count = 0
                    self._available = True
                    logger.info(f"Redis快速降级窗口过期，恢复正常检查模式")
                    
        if not self._available:
            self._check_availability()
            if not self._available:
                self._misses += 1
                return None
        
        try:
            with self._get_connection() as conn:
                value = conn.get(key)
                if value is None:
                    self._misses += 1
                    return None
                
                self._hits += 1
                self._failure_count = 0
                self._consecutive_degradations = 0
                return self._deserialize(value)
                
        except Exception as e:
            self._handle_error(e, "GET")
            self._misses += 1
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存值"""
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            if elapsed <= self.degradation_config.quick_degradation_window:
                self._misses += 1
                logger.debug(f"Redis快速降级模式，跳过SET操作，剩余时间: {self.degradation_config.quick_degradation_window - elapsed:.1f}s")
                return False
            else:
                logger.info(f"Redis快速降级窗口过期，执行探测检查")
                if not self._probe_redis():
                    logger.warning(f"Redis探测检查失败，继续快速降级模式")
                    self._quick_degradation_mode = True
                    self._degradation_start_time = time.time()
                    self._consecutive_degradations += 1
                    return False
                else:
                    self._quick_degradation_mode = False
                    self._failure_count = 0
                    self._available = True
                    logger.info(f"Redis快速降级窗口过期，恢复正常检查模式")
        
        if not self._available:
            self._check_availability()
            if not self._available:
                return False
        
        try:
            with self._get_connection() as conn:
                serialized = self._serialize(value)
                result = conn.set(key, serialized, ex=ttl)
                self._failure_count = 0
                self._consecutive_degradations = 0
                return bool(result)
                
        except Exception as e:
            self._handle_error(e, "SET")
            return False
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            if elapsed <= self.degradation_config.quick_degradation_window:
                logger.debug(f"Redis快速降级模式，跳过Delete操作，剩余时间: {self.degradation_config.quick_degradation_window - elapsed:.1f}s")
                return False
            else:
                logger.info(f"Redis快速降级窗口过期，执行探测检查")
                if not self._probe_redis():
                    logger.warning(f"Redis探测检查失败，继续快速降级模式")
                    self._quick_degradation_mode = True
                    self._degradation_start_time = time.time()
                    self._consecutive_degradations += 1
                    return False
                else:
                    self._quick_degradation_mode = False
                    self._failure_count = 0
                    self._available = True
                    logger.info(f"Redis快速降级窗口过期，恢复正常检查模式")
        
        if not self._available:
            self._check_availability()
            if not self._available:
                return False
        
        try:
            with self._get_connection() as conn:
                result = conn.delete(key)
                self._failure_count = 0
                return result > 0
                
        except Exception as e:
            self._handle_error(e, "DELETE")
            return False
    
    def exists(self, key: str) -> bool:
        """检查键是否存在"""
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            if elapsed <= self.degradation_config.quick_degradation_window:
                return False
            else:
                self._quick_degradation_mode = False
                self._failure_count = 0
                logger.info(f"Redis快速降级窗口过期，恢复正常检查模式")
        
        if not self._available:
            return False
        
        try:
            with self._get_connection() as conn:
                return conn.exists(key) > 0
        except Exception:
            return False
    
    def clear(self) -> None:
        """清空当前数据库"""
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            if elapsed <= self.degradation_config.quick_degradation_window:
                logger.debug(f"Redis快速降级模式，跳过CLEAR操作")
                return
            else:
                self._quick_degradation_mode = False
                self._failure_count = 0
                logger.info(f"Redis快速降级窗口过期，恢复正常检查模式")
        
        if not self._available:
            return
        
        try:
            with self._get_connection() as conn:
                conn.flushdb()
                self._failure_count = 0
        except Exception as e:
            self._handle_error(e, "FLUSHDB")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        stats = {
            "available": self._available,
            "hits": self._hits,
            "misses": self._misses,
            "errors": self._errors,
            "failure_count": self._failure_count,
            "quick_degradation_mode": self._quick_degradation_mode,
            "degradation_start_time": self._degradation_start_time,
        }
        
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            stats["degradation_remaining_time"] = max(
                0, self.degradation_config.quick_degradation_window - elapsed
            )
        
        if self._available and self._client:
            try:
                info = self._client.info()
                stats.update({
                    "used_memory": info.get("used_memory_human", "N/A"),
                    "connected_clients": info.get("connected_clients", 0),
                    "keyspace_hits": info.get("keyspace_hits", 0),
                    "keyspace_misses": info.get("keyspace_misses", 0),
                })
            except Exception:
                stats["info_error"] = "无法获取Redis信息"
        
        return stats
    
    def keys(self, pattern: str = "*") -> List[str]:
        """根据模式查找键"""
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            if elapsed <= self.degradation_config.quick_degradation_window:
                logger.debug(f"Redis快速降级模式，跳过KEYS操作，剩余时间: {self.degradation_config.quick_degradation_window - elapsed:.1f}s")
                return []
            else:
                self._quick_degradation_mode = False
                self._failure_count = 0
                logger.info(f"Redis快速降级窗口过期，恢复正常检查模式")
        
        if not self._available:
            return []
        
        try:
            with self._get_connection() as conn:
                result = conn.keys(pattern)
                return [k.decode('utf-8') if isinstance(k, bytes) else k for k in result]
        except Exception as e:
            self._handle_error(e, "KEYS")
            return []
    
    def delete_pattern(self, pattern: str) -> int:
        """根据模式删除键"""
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            if elapsed <= self.degradation_config.quick_degradation_window:
                logger.debug(f"Redis快速降级模式，跳过DELETE_PATTERN操作: {pattern}")
                return 0
            else:
                self._quick_degradation_mode = False
                self._failure_count = 0
                logger.info(f"Redis快速降级窗口过期，恢复正常检查模式")
        
        keys = self.keys(pattern)
        if not keys:
            return 0
        
        try:
            with self._get_connection() as conn:
                result = conn.delete(*keys)
                self._failure_count = 0
                return result
        except Exception as e:
            self._handle_error(e, "DELETE_PATTERN")
            return 0
    
    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """批量获取"""
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            if elapsed <= self.degradation_config.quick_degradation_window:
                logger.debug(f"Redis快速降级模式，跳过MGET操作")
                return {}
            else:
                self._quick_degradation_mode = False
                self._failure_count = 0
                logger.info(f"Redis快速降级窗口过期，恢复正常检查模式")
        
        if not self._available or not keys:
            return {}
        
        try:
            with self._get_connection() as conn:
                values = conn.mget(keys)
                return {
                    k: self._deserialize(v) 
                    for k, v in zip(keys, values) 
                    if v is not None
                }
        except Exception as e:
            self._handle_error(e, "MGET")
            return {}
    
    def set_many(self, mapping: Dict[str, Any], ttl: Optional[int] = None) -> int:
        """批量设置"""
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            if elapsed <= self.degradation_config.quick_degradation_window:
                logger.debug(f"Redis快速降级模式，跳过MSET操作")
                return 0
            else:
                self._quick_degradation_mode = False
                self._failure_count = 0
                logger.info(f"Redis快速降级窗口过期，恢复正常检查模式")
        
        if not self._available or not mapping:
            return 0
        
        try:
            with self._get_connection() as conn:
                if ttl:
                    pipe = conn.pipeline()
                    for k, v in mapping.items():
                        pipe.setex(k, ttl, self._serialize(v))
                    pipe.execute()
                else:
                    serialized = {k: self._serialize(v) for k, v in mapping.items()}
                    conn.mset(serialized)
                
                self._failure_count = 0
                return len(mapping)
        except Exception as e:
            self._handle_error(e, "MSET")
            return 0
    
    def incr(self, key: str, amount: int = 1) -> int:
        """原子递增"""
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            if elapsed <= self.degradation_config.quick_degradation_window:
                return 0
            else:
                self._quick_degradation_mode = False
                self._failure_count = 0
                logger.info(f"Redis快速降级窗口过期，恢复正常检查模式")
        
        if not self._available:
            return 0
        
        try:
            with self._get_connection() as conn:
                result = conn.incr(key, amount)
                self._failure_count = 0
                return result
        except Exception as e:
            self._handle_error(e, "INCR")
            return 0
    
    def expire(self, key: str, seconds: int) -> bool:
        """设置过期时间"""
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            if elapsed <= self.degradation_config.quick_degradation_window:
                return False
            else:
                self._quick_degradation_mode = False
                self._failure_count = 0
                logger.info(f"Redis快速降级窗口过期，恢复正常检查模式")
        
        if not self._available:
            return False
        
        try:
            with self._get_connection() as conn:
                result = conn.expire(key, seconds)
                self._failure_count = 0
                return result
        except Exception as e:
            self._handle_error(e, "EXPIRE")
            return False
    
    def ttl(self, key: str) -> int:
        """获取剩余过期时间"""
        if self._quick_degradation_mode:
            elapsed = time.time() - self._degradation_start_time
            if elapsed <= self.degradation_config.quick_degradation_window:
                return -2
            else:
                self._quick_degradation_mode = False
                self._failure_count = 0
                logger.info(f"Redis快速降级窗口过期，恢复正常检查模式")
        
        if not self._available:
            return -2
        
        try:
            with self._get_connection() as conn:
                return conn.ttl(key)
        except Exception as e:
            self._handle_error(e, "TTL")
            return -2
    
    def close(self) -> None:
        """关闭连接"""
        if self._pool:
            self._pool.disconnect()
            self._pool = None
            self._client = None
            logger.info("Redis连接池已关闭")


class MultiLevelCache:
    """
    多级缓存管理器
    
    支持 L1(内存) -> L2(Redis) -> L3(数据库) 三级缓存架构
    """
    
    def __init__(self, config: CacheConfig = None):
        self.config = config or CacheConfig()
        
        self._l1_cache = MemoryCache(self.config.memory_config)
        self._l2_cache: Optional[RedisCache] = None
        
        if self.config.degradation_config.enable_l2_fallback:
            try:
                self._l2_cache = RedisCache(
                    self.config.redis_config,
                    self.config.degradation_config
                )
            except Exception as e:
                logger.warning(f"Redis初始化失败，将仅使用L1缓存: {str(e)}")
        
        self._enabled = True
        self._metrics = {
            "l1_hits": 0,
            "l1_misses": 0,
            "l2_hits": 0,
            "l2_misses": 0,
            "l3_hits": 0,
            "l3_misses": 0,
            "total_requests": 0,
        }
    
    @property
    def l1(self) -> MemoryCache:
        """获取L1缓存"""
        return self._l1_cache
    
    @property
    def l2(self) -> Optional[RedisCache]:
        """获取L2缓存"""
        return self._l2_cache
    
    def get(
        self,
        key: str,
        loader: Optional[Callable[[], Any]] = None,
        ttl: Optional[int] = None,
    ) -> Optional[Any]:
        """
        多级缓存获取
        
        Args:
            key: 缓存键
            loader: 数据加载函数(L3回源)
            ttl: 过期时间
        
        Returns:
            缓存值或None
        """
        if not self._enabled:
            if loader:
                return loader()
            return None
        
        self._metrics["total_requests"] += 1
        actual_ttl = ttl or self.config.ttl_config.default
        
        value = self._l1_cache.get(key)
        if value is not None:
            self._metrics["l1_hits"] += 1
            return value if value != "__NULL__" else None
        
        self._metrics["l1_misses"] += 1
        
        if self._l2_cache and self._l2_cache.is_available:
            value = self._l2_cache.get(key)
            if value is not None:
                self._metrics["l2_hits"] += 1
                self._l1_cache.set(key, value, self.config.ttl_config.l1_ttl)
                return value if value != "__NULL__" else None
        
        self._metrics["l2_misses"] += 1
        
        if loader:
            value = loader()
            self._metrics["l3_hits"] += 1
            
            if value is None and self.config.protection_config.enable_penetration_protection:
                self._set_cache(key, "__NULL__", self.config.ttl_config.null_value_ttl)
            elif value is not None:
                self._set_cache(key, value, actual_ttl)
            
            return value
        
        self._metrics["l3_misses"] += 1
        return None
    
    def _set_cache(self, key: str, value: Any, ttl: int) -> None:
        """设置到多级缓存"""
        l1_ttl = min(ttl, self.config.ttl_config.l1_ttl) if self.config.ttl_config.l1_ttl > 0 else ttl
        self._l1_cache.set(key, value, l1_ttl)
        
        if self._l2_cache and self._l2_cache.is_available:
            l2_ttl = self.config.ttl_config.get_ttl_with_jitter(ttl)
            self._l2_cache.set(key, value, l2_ttl)
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存"""
        actual_ttl = ttl or self.config.ttl_config.default
        self._set_cache(key, value, actual_ttl)
        return True
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        self._l1_cache.delete(key)
        
        if self._l2_cache:
            self._l2_cache.delete(key)
        
        return True
    
    def delete_pattern(self, pattern: str) -> int:
        """根据模式删除缓存"""
        count = 0
        
        # 使用 fnmatch 进行模式匹配，支持通配符
        l1_keys = [k for k in self._l1_cache.keys() if fnmatch.fnmatch(k, pattern)]
        for k in l1_keys:
            if self._l1_cache.delete(k):
                count += 1
        
        if self._l2_cache and self._l2_cache.is_available:
            count += self._l2_cache.delete_pattern(pattern)
        
        return count
    
    def clear(self) -> None:
        """清空所有缓存"""
        self._l1_cache.clear()
        
        if self._l2_cache:
            self._l2_cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total = self._metrics["total_requests"]
        l1_total = self._metrics["l1_hits"] + self._metrics["l1_misses"]
        l2_total = self._metrics["l2_hits"] + self._metrics["l2_misses"]
        
        return {
            "enabled": self._enabled,
            "l1_stats": self._l1_cache.get_stats(),
            "l2_stats": self._l2_cache.get_stats() if self._l2_cache else None,
            "metrics": {
                **self._metrics,
                "l1_hit_rate": f"{(self._metrics['l1_hits'] / l1_total * 100) if l1_total > 0 else 0:.2f}%",
                "l2_hit_rate": f"{(self._metrics['l2_hits'] / l2_total * 100) if l2_total > 0 else 0:.2f}%",
            }
        }
    
    def enable(self) -> None:
        """启用缓存"""
        self._enabled = True
    
    def disable(self) -> None:
        """禁用缓存"""
        self._enabled = False
    
    def is_enabled(self) -> bool:
        """检查是否启用"""
        return self._enabled


class CacheManager:
    """
    高级缓存管理器
    
    提供完整的缓存管理功能，包括:
    - 多级缓存
    - 防护机制
    - 降级处理
    - 性能监控
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, config: CacheConfig = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, config: CacheConfig = None):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self.config = config or CacheConfig()
        self._cache = MultiLevelCache(self.config)
        self._initialized = True
    
    def get(
        self,
        key: str,
        loader: Optional[Callable[[], Any]] = None,
        ttl: Optional[int] = None,
    ) -> Optional[Any]:
        """获取缓存"""
        return self._cache.get(key, loader, ttl)
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存"""
        return self._cache.set(key, value, ttl)
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        return self._cache.delete(key)
    
    def delete_pattern(self, pattern: str) -> int:
        """根据模式删除"""
        return self._cache.delete_pattern(pattern)
    
    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计"""
        return self._cache.get_stats()
    
    def enable(self) -> None:
        """启用缓存"""
        self._cache.enable()
    
    def disable(self) -> None:
        """禁用缓存"""
        self._cache.disable()
    
    @classmethod
    def get_instance(cls) -> "CacheManager":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
