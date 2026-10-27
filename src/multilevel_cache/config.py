"""
配置模块 - 定义缓存配置、策略和枚举
"""

import logging
import os
from enum import Enum
from typing import Optional, Dict, Any, List, Callable, Set
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


def _warn_unknown_keys(section: str, data: Dict[str, Any], known: Set[str]) -> None:
    """MLC-05: 对配置段的未知键告警，拼写错误(如 socket_connect_connect_timeout)
    过去会静默丢失或抛出难定位的 TypeError"""
    unknown = set(data) - known
    if unknown:
        logger.warning(
            f"CacheConfig 段 '{section}' 含未知键并被忽略: {sorted(unknown)}; "
            f"已知键: {sorted(known)}"
        )


class CacheLevel(Enum):
    """缓存层级"""
    L1_MEMORY = "l1_memory"
    L2_REDIS = "l2_redis"
    L3_DATABASE = "l3_database"


class CacheStrategy(Enum):
    """缓存策略"""
    READ_THROUGH = "read_through"
    WRITE_THROUGH = "write_through"
    WRITE_BEHIND = "write_behind"
    REFRESH_AHEAD = "refresh_ahead"


class EvictionPolicy(Enum):
    """淘汰策略"""
    LRU = "lru"
    LFU = "lfu"
    FIFO = "fifo"
    TTL = "ttl"


@dataclass
class TTLConfig:
    """TTL配置"""
    default: int = 300
    l1_ttl: int = 300
    l2_ttl: int = 1800
    null_value_ttl: int = 60
    lock_timeout: int = 10
    
    jitter_min: float = 0.9
    jitter_max: float = 1.1
    
    def get_ttl_with_jitter(self, ttl: int) -> int:
        """获取带随机抖动的TTL"""
        import random
        if ttl <= 0:
            return ttl
        jitter = random.uniform(self.jitter_min, self.jitter_max)
        return int(ttl * jitter)


@dataclass
class RedisConfig:
    """Redis配置"""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    ssl: bool = False
    socket_timeout: int = 5
    socket_connect_timeout: int = 5
    max_connections: int = 50
    decode_responses: bool = True
    
    def __post_init__(self):
        """从环境变量加载配置（优先级高于默认值）"""
        self.host = os.getenv("REDIS_HOST", self.host)
        self.port = int(os.getenv("REDIS_PORT", str(self.port)))
        self.db = int(os.getenv("REDIS_DB", str(self.db)))
        self.password = os.getenv("REDIS_PASSWORD", self.password)
        self.ssl = os.getenv("REDIS_SSL", str(self.ssl)).lower() == "true"
        self.socket_timeout = int(os.getenv("REDIS_SOCKET_TIMEOUT", str(self.socket_timeout)))
        self.socket_connect_timeout = int(os.getenv("REDIS_SOCKET_CONNECT_TIMEOUT", str(self.socket_connect_timeout)))
        self.max_connections = int(os.getenv("REDIS_MAX_CONNECTIONS", str(self.max_connections)))
        self.decode_responses = os.getenv("REDIS_DECODE_RESPONSES", str(self.decode_responses)).lower() == "true"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "db": self.db,
            "password": self.password,
            "ssl": self.ssl,
            "socket_timeout": self.socket_timeout,
            "socket_connect_timeout": self.socket_connect_timeout,
            "max_connections": self.max_connections,
            "decode_responses": self.decode_responses,
        }


@dataclass
class MemoryCacheConfig:
    """内存缓存配置"""
    max_size: int = 1000
    default_ttl: int = 300
    eviction_policy: EvictionPolicy = EvictionPolicy.LRU
    thread_safe: bool = True


@dataclass
class ProtectionConfig:
    """缓存防护配置"""
    enable_penetration_protection: bool = True
    enable_breakdown_protection: bool = True
    enable_bloom_filter: bool = False
    bloom_filter_size: int = 100000
    bloom_filter_hashes: int = 7
    max_retry_attempts: int = 3
    retry_delay: float = 0.1


@dataclass
class DegradationConfig:
    """降级配置"""
    enable_auto_degradation: bool = True
    failure_threshold: int = 3
    recovery_check_interval: int = 30
    enable_l2_fallback: bool = True
    quick_degradation_window: int = 60


@dataclass
class CacheConfig:
    """缓存总配置"""
    name: str = "default"
    strategy: CacheStrategy = CacheStrategy.READ_THROUGH
    
    memory_config: MemoryCacheConfig = field(default_factory=MemoryCacheConfig)
    redis_config: RedisConfig = field(default_factory=RedisConfig)
    ttl_config: TTLConfig = field(default_factory=TTLConfig)
    protection_config: ProtectionConfig = field(default_factory=ProtectionConfig)
    degradation_config: DegradationConfig = field(default_factory=DegradationConfig)
    
    enable_metrics: bool = True
    enable_logging: bool = True
    log_level: str = "INFO"
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheConfig":
        """从字典创建配置"""
        config = cls(name=data.get("name", "default"))
        
        if "strategy" in data:
            config.strategy = CacheStrategy(data["strategy"])
        
        if "memory" in data:
            mc = data["memory"]
            _warn_unknown_keys(
                "memory", mc,
                {"max_size", "default_ttl", "eviction_policy", "thread_safe"},
            )
            config.memory_config = MemoryCacheConfig(
                max_size=mc.get("max_size", 1000),
                default_ttl=mc.get("default_ttl", 300),
                eviction_policy=EvictionPolicy(mc.get("eviction_policy", "lru")),
                thread_safe=mc.get("thread_safe", True),
            )
        
        if "redis" in data:
            rc = data["redis"]
            _warn_unknown_keys(
                "redis", rc,
                {"host", "port", "db", "password", "ssl", "socket_timeout",
                 "socket_connect_timeout", "max_connections", "decode_responses"},
            )
            config.redis_config = RedisConfig(
                host=rc.get("host", "localhost"),
                port=rc.get("port", 6379),
                db=rc.get("db", 0),
                password=rc.get("password"),
                ssl=rc.get("ssl", False),
                socket_timeout=rc.get("socket_timeout", 5),
                # MLC-05: 原为 socket_connect_connect_timeout（拼写错误），
                # dataclass 不接收未知字段，配置了 redis 段必然 TypeError
                socket_connect_timeout=rc.get("socket_connect_timeout", 5),
                max_connections=rc.get("max_connections", 50),
                decode_responses=rc.get("decode_responses", True),
            )
        
        if "ttl" in data:
            tc = data["ttl"]
            _warn_unknown_keys(
                "ttl", tc,
                {"default", "l1_ttl", "l2_ttl", "null_value_ttl",
                 "lock_timeout", "jitter_min", "jitter_max"},
            )
            config.ttl_config = TTLConfig(
                default=tc.get("default", 300),
                l1_ttl=tc.get("l1_ttl", 300),
                l2_ttl=tc.get("l2_ttl", 1800),
                null_value_ttl=tc.get("null_value_ttl", 60),
                lock_timeout=tc.get("lock_timeout", 10),
                jitter_min=tc.get("jitter_min", 0.9),
                jitter_max=tc.get("jitter_max", 1.1),
            )
        
        if "protection" in data:
            pc = data["protection"]
            config.protection_config = ProtectionConfig(
                enable_penetration_protection=pc.get("enable_penetration_protection", True),
                enable_breakdown_protection=pc.get("enable_breakdown_protection", True),
                enable_bloom_filter=pc.get("enable_bloom_filter", False),
                bloom_filter_size=pc.get("bloom_filter_size", 100000),
                bloom_filter_hashes=pc.get("bloom_filter_hashes", 7),
                max_retry_attempts=pc.get("max_retry_attempts", 3),
                retry_delay=pc.get("retry_delay", 0.1),
            )
        
        if "degradation" in data:
            dc = data["degradation"]
            config.degradation_config = DegradationConfig(
                enable_auto_degradation=dc.get("enable_auto_degradation", True),
                failure_threshold=dc.get("failure_threshold", 3),
                recovery_check_interval=dc.get("recovery_check_interval", 30),
                enable_l2_fallback=dc.get("enable_l2_fallback", True),
                # MLC-05: 原先漏传该字段，配置文件里的 quick_degradation_window
                # 静默丢弃，快速降级窗口永远是默认 60s
                quick_degradation_window=dc.get("quick_degradation_window", 60),
            )
        
        config.enable_metrics = data.get("enable_metrics", True)
        config.enable_logging = data.get("enable_logging", True)
        config.log_level = data.get("log_level", "INFO")
        
        return config


class CacheKeyBuilder:
    """缓存键构建器"""
    
    SEPARATOR = ":"
    VERSION = "v1"
    
    @classmethod
    def build(
        cls,
        prefix: str,
        identifier: Any,
        *extra_parts: Any
    ) -> str:
        """
        构建缓存键
        
        格式: version:prefix:identifier[:extra_parts...]
        """
        parts = [cls.VERSION, prefix, str(identifier)]
        if extra_parts:
            parts.extend(str(p) for p in extra_parts)
        return cls.SEPARATOR.join(parts)
    
    @classmethod
    def build_pattern(cls, prefix: str, *extra_parts: Any) -> str:
        """构建缓存键匹配模式"""
        parts = [cls.VERSION, prefix]
        if extra_parts:
            parts.extend(str(p) for p in extra_parts)
        parts.append("*")
        return cls.SEPARATOR.join(parts)
    
    @classmethod
    def parse(cls, key: str) -> Dict[str, Any]:
        """解析缓存键"""
        parts = key.split(cls.SEPARATOR)
        return {
            "version": parts[0] if len(parts) > 0 else None,
            "prefix": parts[1] if len(parts) > 1 else None,
            "identifier": parts[2] if len(parts) > 2 else None,
            "extra": parts[3:] if len(parts) > 3 else []
        }
