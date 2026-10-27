"""
多级缓存模块 (Multi-Level Cache Module)

一个可独立安装、复用的多级缓存Python包，支持：
- L1: 本地内存缓存
- L2: Redis分布式缓存  
- L3: 数据库回源

特性:
- 缓存穿透、击穿、雪崩防护
- 自动降级处理
- 分布式锁支持
- 性能监控与统计
- 灵活的配置系统
- MQ跨服务器同步
- 版本控制机制
- 业务失效规则
- 资源监控限制
"""

from multilevel_cache.core import (
    CacheBackend,
    MemoryCache,
    RedisCache,
    MultiLevelCache,
    CacheManager,
    CacheEntry,
)
from multilevel_cache.config import (
    CacheConfig,
    MemoryCacheConfig,
    RedisConfig,
    TTLConfig,
    CacheKeyBuilder,
    EvictionPolicy,
    DegradationConfig,
    CacheLevel,
    CacheStrategy,
)
from multilevel_cache.decorators import cached, cached_async
from multilevel_cache.protection import (
    CacheProtection,
    DistributedLock,
    LocalLock,
    BloomFilter,
    CircuitBreaker,
    RateLimiter,
)
from multilevel_cache.monitoring import CacheMetrics, CacheMonitor
from multilevel_cache.sync import (
    MQPublisher,
    MQConsumer,
    CacheSyncManager,
    MQConfig,
    CacheSyncMessage,
)
from multilevel_cache.version import (
    CacheVersionManager,
    VersionInfo,
    VersionedCacheWrapper,
)
from multilevel_cache.invalidation import (
    CacheInvalidationRules,
    CacheInvalidationManager,
    EntityType,
    InvalidationRule,
)
from multilevel_cache.resource import (
    ResourceMonitor,
    ResourceLimits,
    ResourceUsage,
    ResourceAwareCache,
)
from multilevel_cache.integrated import (
    IntegratedCacheManager,
    IntegratedCacheConfig,
)

__version__ = "1.2.0"
__all__ = [
    # 核心组件
    "CacheBackend",
    "MemoryCache", 
    "RedisCache",
    "MultiLevelCache",
    "CacheManager",
    "CacheEntry",
    
    # 配置
    "CacheConfig",
    "MemoryCacheConfig",
    "RedisConfig",
    "TTLConfig",
    "CacheKeyBuilder",
    "EvictionPolicy",
    "DegradationConfig",
    "CacheLevel",
    "CacheStrategy",
    
    # 装饰器
    "cached",
    "cached_async",
    
    # 防护机制
    "CacheProtection",
    "DistributedLock",
    "LocalLock",
    "BloomFilter",
    "CircuitBreaker",
    "RateLimiter",
    
    # 监控
    "CacheMetrics",
    "CacheMonitor",
    
    # MQ同步
    "MQPublisher",
    "MQConsumer",
    "CacheSyncManager",
    "MQConfig",
    "CacheSyncMessage",
    
    # 版本控制
    "CacheVersionManager",
    "VersionInfo",
    "VersionedCacheWrapper",
    
    # 失效规则
    "CacheInvalidationRules",
    "CacheInvalidationManager",
    "EntityType",
    "InvalidationRule",
    
    # 资源监控
    "ResourceMonitor",
    "ResourceLimits",
    "ResourceUsage",
    "ResourceAwareCache",
    
    # 集成管理器
    "IntegratedCacheManager",
    "IntegratedCacheConfig",
]
