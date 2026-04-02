"""
异常模块 - 定义缓存相关的异常类
"""


class CacheError(Exception):
    """缓存基础异常"""
    pass


class CacheConnectionError(CacheError):
    """缓存连接异常"""
    pass


class CacheTimeoutError(CacheError):
    """缓存超时异常"""
    pass


class CacheSerializationError(CacheError):
    """缓存序列化异常"""
    pass


class CacheDeserializationError(CacheError):
    """缓存反序列化异常"""
    pass


class CacheKeyError(CacheError):
    """缓存键异常"""
    pass


class CacheFullError(CacheError):
    """缓存已满异常"""
    pass


class CacheConfigurationError(CacheError):
    """缓存配置异常"""
    pass


class LockAcquireError(CacheError):
    """锁获取异常"""
    pass


class LockReleaseError(CacheError):
    """锁释放异常"""
    pass


class CircuitBreakerOpenError(CacheError):
    """熔断器打开异常"""
    pass


class RateLimitExceededError(CacheError):
    """限流异常"""
    pass


class CacheDegradationError(CacheError):
    """缓存降级异常"""
    pass


class CacheUnavailableError(CacheError):
    """缓存不可用异常"""
    pass
