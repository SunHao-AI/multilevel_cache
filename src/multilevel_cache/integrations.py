"""
第三方缓存库集成适配器

本模块提供与主流缓存库的集成适配器，支持：
- cacheout: 功能丰富的Python缓存库
- aiocache: 异步缓存库
- dogpile.cache: 强大的缓存库，支持多种后端
- Flask-Caching: Flask缓存扩展

使用适配器模式，统一不同缓存库的接口。
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class CacheAdapter(ABC):
    """缓存适配器抽象基类"""
    
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
    def clear(self) -> None:
        """清空缓存"""
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        pass


class CacheoutAdapter(CacheAdapter):
    """
    cacheout库适配器
    
    cacheout是一个功能丰富的Python缓存库，支持：
    - 多种缓存策略（LRU、LFU、TTL等）
    - 缓存管理器
    - 缓存代理
    
    安装: pip install cacheout
    
    示例:
        from cacheout import Cache
        cache = Cache(maxsize=1000, ttl=300)
        adapter = CacheoutAdapter(cache)
    """
    
    def __init__(self, cache=None, maxsize: int = 1000, ttl: int = 300):
        self._cache = cache
        self._maxsize = maxsize
        self._default_ttl = ttl
        
        if self._cache is None:
            try:
                from cacheout import Cache
                self._cache = Cache(maxsize=maxsize, ttl=ttl)
            except ImportError:
                logger.warning("cacheout库未安装，请运行: pip install cacheout")
                raise
    
    def get(self, key: str) -> Optional[Any]:
        return self._cache.get(key)
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        try:
            self._cache.set(key, value, ttl=ttl or self._default_ttl)
            return True
        except Exception as e:
            logger.error(f"cacheout set错误: {str(e)}")
            return False
    
    def delete(self, key: str) -> bool:
        try:
            self._cache.delete(key)
            return True
        except Exception:
            return False
    
    def clear(self) -> None:
        self._cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "size": len(self._cache),
            "maxsize": self._maxsize,
            "ttl": self._default_ttl,
        }
    
    def keys(self) -> List[str]:
        return list(self._cache.keys())
    
    def has(self, key: str) -> bool:
        return key in self._cache


class AiocacheAdapter(CacheAdapter):
    """
    aiocache库适配器
    
    aiocache是一个异步缓存库，支持：
    - Redis、Memcached、内存后端
    - 异步API
    - 序列化支持
    - 装饰器
    
    安装: pip install aiocache
    
    示例:
        from aiocache import Cache
        from aiocache.serializers import PickleSerializer
        
        cache = Cache(Cache.REDIS, endpoint="localhost", port=6379)
        adapter = AiocacheAdapter(cache)
    """
    
    def __init__(self, cache=None, backend: str = "memory", **kwargs):
        self._cache = cache
        self._backend = backend
        
        if self._cache is None:
            try:
                from aiocache import Cache
                
                if backend == "redis":
                    self._cache = Cache(
                        Cache.REDIS,
                        endpoint=kwargs.get("host", "localhost"),
                        port=kwargs.get("port", 6379),
                        timeout=kwargs.get("timeout", 5),
                    )
                elif backend == "memcached":
                    self._cache = Cache(
                        Cache.MEMCACHED,
                        endpoint=kwargs.get("host", "localhost"),
                        port=kwargs.get("port", 11211),
                    )
                else:
                    self._cache = Cache()
            except ImportError:
                logger.warning("aiocache库未安装，请运行: pip install aiocache")
                raise
    
    def get(self, key: str) -> Optional[Any]:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(self._cache.get(key))
        except Exception as e:
            logger.error(f"aiocache get错误: {str(e)}")
            return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self._cache.set(key, value, ttl=ttl))
            return True
        except Exception as e:
            logger.error(f"aiocache set错误: {str(e)}")
            return False
    
    def delete(self, key: str) -> bool:
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            loop.run_until_complete(self._cache.delete(key))
            return True
        except Exception:
            return False
    
    def clear(self) -> None:
        import asyncio
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self._cache.clear())
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "backend": self._backend,
        }
    
    async def async_get(self, key: str) -> Optional[Any]:
        """异步获取"""
        return await self._cache.get(key)
    
    async def async_set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """异步设置"""
        try:
            await self._cache.set(key, value, ttl=ttl)
            return True
        except Exception:
            return False
    
    async def async_delete(self, key: str) -> bool:
        """异步删除"""
        try:
            await self._cache.delete(key)
            return True
        except Exception:
            return False


class DogpileCacheAdapter(CacheAdapter):
    """
    dogpile.cache库适配器
    
    dogpile.cache是一个强大的缓存库，支持：
    - 多种后端（Redis、Memcached、数据库等）
    - 区域管理
    - 缓存装饰器
    - 狗狗门锁模式（防止缓存击穿）
    
    安装: pip install dogpile.cache
    
    示例:
        from dogpile.cache import make_region
        
        region = make_region().configure(
            'dogpile.cache.redis',
            arguments={
                'host': 'localhost',
                'port': 6379,
                'db': 0,
            }
        )
        adapter = DogpileCacheAdapter(region)
    """
    
    def __init__(self, region=None, backend: str = "memory", **kwargs):
        self._region = region
        self._backend = backend
        
        if self._region is None:
            try:
                from dogpile.cache import make_region
                
                if backend == "redis":
                    self._region = make_region().configure(
                        'dogpile.cache.redis',
                        arguments={
                            'host': kwargs.get("host", "localhost"),
                            'port': kwargs.get("port", 6379),
                            'db': kwargs.get("db", 0),
                            'redis_expiration_time': kwargs.get("ttl", 3600),
                        }
                    )
                else:
                    self._region = make_region().configure(
                        'dogpile.cache.memory',
                        expiration_time=kwargs.get("ttl", 300),
                    )
            except ImportError:
                logger.warning("dogpile.cache库未安装，请运行: pip install dogpile.cache")
                raise
    
    def get(self, key: str) -> Optional[Any]:
        return self._region.get(key)
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        try:
            self._region.set(key, value)
            return True
        except Exception as e:
            logger.error(f"dogpile set错误: {str(e)}")
            return False
    
    def delete(self, key: str) -> bool:
        try:
            self._region.delete(key)
            return True
        except Exception:
            return False
    
    def clear(self) -> None:
        try:
            self._region.invalidate()
        except Exception as e:
            logger.error(f"dogpile clear错误: {str(e)}")
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "backend": self._backend,
        }
    
    def get_or_create(
        self,
        key: str,
        creator: Callable,
        expiration_time: Optional[int] = None
    ) -> Any:
        """
        获取或创建缓存值
        
        使用dogpile的狗狗门锁模式，防止缓存击穿
        """
        return self._region.get_or_create(
            key,
            creator,
            expiration_time=expiration_time
        )


class FlaskCachingAdapter(CacheAdapter):
    """
    Flask-Caching适配器
    
    Flask-Caching是Flask的缓存扩展，支持：
    - 多种后端（Redis、Memcached、FileSystem等）
    - Flask应用集成
    - 缓存装饰器
    
    安装: pip install Flask-Caching
    
    示例:
        from flask import Flask
        from flask_caching import Cache
        
        app = Flask(__name__)
        cache = Cache(app, config={'CACHE_TYPE': 'RedisCache'})
        adapter = FlaskCachingAdapter(cache)
    """
    
    def __init__(self, cache=None, app=None, config=None):
        self._cache = cache
        
        if self._cache is None:
            try:
                from flask_caching import Cache
                
                if app:
                    self._cache = Cache(app, config=config)
                else:
                    self._cache = Cache(config=config)
            except ImportError:
                logger.warning("Flask-Caching库未安装，请运行: pip install Flask-Caching")
                raise
    
    def get(self, key: str) -> Optional[Any]:
        return self._cache.get(key)
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        try:
            self._cache.set(key, value, timeout=ttl)
            return True
        except Exception as e:
            logger.error(f"Flask-Caching set错误: {str(e)}")
            return False
    
    def delete(self, key: str) -> bool:
        try:
            self._cache.delete(key)
            return True
        except Exception:
            return False
    
    def clear(self) -> None:
        self._cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        return {
            "type": "flask-caching",
        }
    
    def cached(
        self,
        timeout: Optional[int] = None,
        key_prefix: str = None
    ):
        """Flask-Caching装饰器"""
        return self._cache.cached(timeout=timeout, key_prefix=key_prefix)
    
    def memoize(self, timeout: Optional[int] = None):
        """记忆化装饰器"""
        return self._cache.memoize(timeout=timeout)


def create_adapter(
    library: str = "cacheout",
    **kwargs
) -> CacheAdapter:
    """
    创建缓存适配器
    
    Args:
        library: 缓存库名称 (cacheout, aiocache, dogpile, flask-caching)
        **kwargs: 传递给缓存库的配置参数
    
    Returns:
        CacheAdapter实例
    
    示例:
        # 使用cacheout
        adapter = create_adapter("cacheout", maxsize=1000, ttl=300)
        
        # 使用aiocache
        adapter = create_adapter("aiocache", backend="redis", host="localhost")
        
        # 使用dogpile
        adapter = create_adapter("dogpile", backend="redis", host="localhost")
    """
    adapters = {
        "cacheout": CacheoutAdapter,
        "aiocache": AiocacheAdapter,
        "dogpile": DogpileCacheAdapter,
        "dogpile.cache": DogpileCacheAdapter,
        "flask-caching": FlaskCachingAdapter,
        "flask_caching": FlaskCachingAdapter,
    }
    
    adapter_cls = adapters.get(library.lower())
    
    if adapter_cls is None:
        raise ValueError(f"不支持的缓存库: {library}。支持的库: {list(adapters.keys())}")
    
    return adapter_cls(**kwargs)


class ThirdPartyCacheManager:
    """
    第三方缓存管理器
    
    统一管理多个第三方缓存适配器
    """
    
    def __init__(self):
        self._adapters: Dict[str, CacheAdapter] = {}
    
    def register(self, name: str, adapter: CacheAdapter) -> None:
        """注册适配器"""
        self._adapters[name] = adapter
        logger.info(f"注册缓存适配器: {name}")
    
    def get_adapter(self, name: str) -> Optional[CacheAdapter]:
        """获取适配器"""
        return self._adapters.get(name)
    
    def get(self, name: str, key: str) -> Optional[Any]:
        """从指定适配器获取缓存"""
        adapter = self.get_adapter(name)
        if adapter:
            return adapter.get(key)
        return None
    
    def set(self, name: str, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存到指定适配器"""
        adapter = self.get_adapter(name)
        if adapter:
            return adapter.set(key, value, ttl)
        return False
    
    def delete(self, name: str, key: str) -> bool:
        """从指定适配器删除缓存"""
        adapter = self.get_adapter(name)
        if adapter:
            return adapter.delete(key)
        return False
    
    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有适配器的统计信息"""
        return {
            name: adapter.get_stats()
            for name, adapter in self._adapters.items()
        }
