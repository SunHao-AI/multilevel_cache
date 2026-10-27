"""
缓存装饰器模块 - 提供便捷的缓存装饰器
"""

import asyncio
import functools
import hashlib
import json
import logging
import threading
import time
import weakref
from typing import Any, Callable, Optional, Union

logger = logging.getLogger(__name__)


def _generate_cache_key(
    prefix: str,
    func: Callable,
    args: tuple,
    kwargs: dict
) -> str:
    """生成缓存键"""
    key_parts = [prefix, func.__name__]
    
    if args:
        key_parts.extend(str(arg) for arg in args)
    
    if kwargs:
        sorted_kwargs = sorted(kwargs.items())
        key_parts.extend(f"{k}={v}" for k, v in sorted_kwargs)
    
    key_str = ":".join(key_parts)
    
    if len(key_str) > 200:
        return f"{prefix}:{func.__name__}:{hashlib.md5(key_str.encode()).hexdigest()}"
    
    return key_str


def cached(
    cache_manager=None,
    key_prefix: str = "",
    ttl: Optional[int] = None,
    key_builder: Optional[Callable] = None,
):
    """
    同步缓存装饰器
    
    Args:
        cache_manager: 缓存管理器实例
        key_prefix: 缓存键前缀
        ttl: 过期时间（秒）
        key_builder: 自定义缓存键构建函数
    
    MLC-07: 原有的 prevent_penetration / prevent_breakdown 参数收下后从未
    传递下游（死参数），已删除。穿透/击穿防护现由 CacheManager.get 主链路
    统一实施（空值哨兵 + 按 key single-flight），由 CacheConfig 的
    protection_config 控制。
    
    Example:
        @cached(key_prefix="user", ttl=300)
        def get_user(user_id: int):
            return db.query(User).get(user_id)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal cache_manager
            
            if cache_manager is None:
                from multilevel_cache.core import CacheManager
                cache_manager = CacheManager.get_instance()
            
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                cache_key = _generate_cache_key(key_prefix, func, args, kwargs)
            
            def loader():
                return func(*args, **kwargs)
            
            return cache_manager.get(
                cache_key,
                loader=loader,
                ttl=ttl,
            )
        
        wrapper.cache_invalidate = lambda *args, **kwargs: _invalidate(
            cache_manager, key_prefix, func, args, kwargs, key_builder
        )
        
        return wrapper
    
    return decorator


def _invalidate(
    cache_manager,
    key_prefix: str,
    func: Callable,
    args: tuple,
    kwargs: dict,
    key_builder: Optional[Callable] = None
) -> bool:
    """使缓存失效"""
    if cache_manager is None:
        from multilevel_cache.core import CacheManager
        cache_manager = CacheManager.get_instance()
    
    if key_builder:
        cache_key = key_builder(*args, **kwargs)
    else:
        cache_key = _generate_cache_key(key_prefix, func, args, kwargs)
    
    return cache_manager.delete(cache_key)


# MLC-07: cached_async 的按 key in-flight 表（事件循环单线程内 get/pop 之间
# 无 await，天然原子；跨任务共享 Future 实现同键并发只回源一次）
_async_inflight: dict = {}


def cached_async(
    cache_manager=None,
    key_prefix: str = "",
    ttl: Optional[int] = None,
    key_builder: Optional[Callable] = None,
):
    """
    异步缓存装饰器
    
    Args:
        cache_manager: 缓存管理器实例
        key_prefix: 缓存键前缀
        ttl: 过期时间（秒）
        key_builder: 自定义缓存键构建函数
    
    MLC-07: 原实现为无锁 check-then-set，热点键过期瞬间全部协程并发回源
    （惊群）。现按 key 共享 in-flight Future，同键并发仅一个协程执行函数。
    
    Example:
        @cached_async(key_prefix="user", ttl=300)
        async def get_user(user_id: int):
            return await db.query(User).get(user_id)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            nonlocal cache_manager
            
            if cache_manager is None:
                from multilevel_cache.core import CacheManager
                cache_manager = CacheManager.get_instance()
            
            if key_builder:
                cache_key = key_builder(*args, **kwargs)
            else:
                cache_key = _generate_cache_key(key_prefix, func, args, kwargs)
            
            cached_value = cache_manager.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            pending = _async_inflight.get(cache_key)
            if pending is not None:
                return await asyncio.shield(pending)
            
            loop = asyncio.get_event_loop()
            fut = loop.create_future()
            _async_inflight[cache_key] = fut
            try:
                result = await func(*args, **kwargs)
                cache_manager.set(cache_key, result, ttl=ttl)
                if not fut.done():
                    fut.set_result(result)
                return result
            except BaseException as exc:
                if not fut.done():
                    fut.set_exception(exc)
                raise
            finally:
                _async_inflight.pop(cache_key, None)
        
        wrapper.cache_invalidate = lambda *args, **kwargs: _invalidate(
            cache_manager, key_prefix, func, args, kwargs, key_builder
        )
        
        return wrapper
    
    return decorator


def cached_method(
    key_prefix: str = "",
    ttl: Optional[int] = None,
    key_builder: Optional[Callable] = None,
):
    """
    方法缓存装饰器
    
    自动处理self参数
    
    Example:
        class UserService:
            @cached_method(key_prefix="user", ttl=300)
            def get_user(self, user_id: int):
                return self.db.query(User).get(user_id)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, *args, **kwargs):
            cache_manager = getattr(self, '_cache_manager', None)
            
            if cache_manager is None:
                from multilevel_cache.core import CacheManager
                cache_manager = CacheManager.get_instance()
            
            if key_builder:
                cache_key = key_builder(self, *args, **kwargs)
            else:
                class_name = self.__class__.__name__
                cache_key = _generate_cache_key(
                    f"{key_prefix}:{class_name}", func, args, kwargs
                )
            
            def loader():
                return func(self, *args, **kwargs)
            
            return cache_manager.get(
                cache_key,
                loader=loader,
                ttl=ttl,
            )
        
        return wrapper
    
    return decorator


def cache_result(
    key: str,
    ttl: int = 300,
    condition: Optional[Callable[[Any], bool]] = None,
):
    """
    结果缓存装饰器
    
    根据条件决定是否缓存结果
    
    Args:
        key: 固定缓存键
        ttl: 过期时间
        condition: 缓存条件函数，返回True时缓存
    
    Example:
        @cache_result("expensive_computation", ttl=600)
        def compute():
            return expensive_operation()
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            from multilevel_cache.core import CacheManager
            cache_manager = CacheManager.get_instance()
            
            cached_value = cache_manager.get(key)
            if cached_value is not None:
                return cached_value
            
            result = func(*args, **kwargs)
            
            should_cache = condition(result) if condition else True
            if should_cache:
                cache_manager.set(key, result, ttl=ttl)
            
            return result
        
        return wrapper
    
    return decorator


def invalidate_cache(
    cache_manager=None,
    patterns: Optional[list] = None,
):
    """
    缓存失效装饰器
    
    在函数执行后使指定模式的缓存失效
    
    Args:
        cache_manager: 缓存管理器实例
        patterns: 要失效的缓存模式列表
    
    Example:
        @invalidate_cache(patterns=["user:*", "users:list"])
        def update_user(user_id: int, data: dict):
            return db.update(User, user_id, data)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal cache_manager
            
            result = func(*args, **kwargs)
            
            if cache_manager is None:
                from multilevel_cache.core import CacheManager
                cache_manager = CacheManager.get_instance()
            
            if patterns:
                for pattern in patterns:
                    cache_manager.delete_pattern(pattern)
            
            return result
        
        return wrapper
    
    return decorator


class CachedProperty:
    """
    缓存属性描述符
    
    类似于functools.cached_property，但支持TTL
    
    MLC-06: 原实现用 `id(instance)` 拼缓存键写入共享 CacheManager。CPython
    会复用已释放对象的内存地址 —— 旧实例被 GC 后，新实例命中旧实例的缓存值
    （且跨类也可能撞 id）。改为每个描述符自持 WeakKeyDictionary：随实例
    销毁自动淘汰，无 id 复用风险，也不会把对象图写进共享 L1/L2。
    
    Example:
        class User:
            @CachedProperty(ttl=300)
            def permissions(self):
                return load_permissions(self.id)
    """
    
    def __init__(self, func: Callable = None, ttl: int = 300):
        self.func = func
        self.ttl = ttl
        self.attr_name = None
        # instance -> (value, expire_at); 弱键，实例销毁即释放
        self._values = weakref.WeakKeyDictionary()
        self._lock = threading.Lock()
    
    def __set_name__(self, owner, name):
        self.attr_name = f"_cached_{name}"
    
    def __get__(self, instance, owner):
        if instance is None:
            return self
        
        if self.func is None:
            raise AttributeError(
                "CachedProperty 尚未绑定函数，请检查装饰器用法"
            )
        
        now = time.time()
        try:
            with self._lock:
                entry = self._values.get(instance)
                if entry is not None and entry[1] > now:
                    return entry[0]
        except TypeError:
            # 实例不可弱引用/不可哈希（如带 __slots__ 的类）：放弃缓存
            return self.func(instance)
        
        result = self.func(instance)
        
        try:
            with self._lock:
                self._values[instance] = (result, now + self.ttl)
        except TypeError:
            pass
        return result
    
    def __call__(self, func: Callable):
        self.func = func
        return self


def cached_property(ttl: int = 300):
    """
    缓存属性装饰器工厂
    
    Example:
        class User:
            @cached_property(ttl=300)
            def permissions(self):
                return load_permissions(self.id)
    """
    return lambda func: CachedProperty(func, ttl)
