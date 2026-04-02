"""
版本控制模块 - 实现缓存版本管理

支持基于版本号的缓存失效机制，确保缓存一致性。
"""

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class VersionInfo:
    """版本信息"""
    entity_type: str
    entity_id: Any
    version: int
    updated_at: float
    updated_by: str = "system"


class CacheVersionManager:
    """
    缓存版本管理器
    
    通过版本号机制管理缓存有效性：
    - 每次数据更新时递增版本号
    - 缓存键包含版本号
    - 版本变化时旧缓存自动失效
    """
    
    VERSION_PREFIX = "version"
    VERSION_SEPARATOR = ":"
    
    def __init__(self, redis_client=None, local_cache: dict = None):
        """
        初始化版本管理器
        
        Args:
            redis_client: Redis客户端（用于分布式版本存储）
            local_cache: 本地缓存字典（用于单机版本存储）
        """
        self._redis = redis_client
        self._local_cache = local_cache or {}
        self._lock = threading.Lock()
        
        self._version_cache: Dict[str, VersionInfo] = {}
    
    def _get_version_key(self, entity_type: str, entity_id: Any) -> str:
        """生成版本键"""
        return f"{self.VERSION_PREFIX}{self.VERSION_SEPARATOR}{entity_type}{self.VERSION_SEPARATOR}{entity_id}"
    
    def get_version(self, entity_type: str, entity_id: Any) -> int:
        """
        获取实体版本号
        
        Args:
            entity_type: 实体类型
            entity_id: 实体ID
        
        Returns:
            当前版本号，不存在返回0
        """
        version_key = self._get_version_key(entity_type, entity_id)
        
        if self._redis:
            try:
                version = self._redis.get(version_key)
                if version:
                    return int(version)
            except Exception as e:
                logger.error(f"获取Redis版本失败: {str(e)}")
        
        with self._lock:
            version_info = self._version_cache.get(version_key)
            return version_info.version if version_info else 0
    
    def increment_version(
        self,
        entity_type: str,
        entity_id: Any,
        updated_by: str = "system"
    ) -> int:
        """
        递增实体版本号
        
        Args:
            entity_type: 实体类型
            entity_id: 实体ID
            updated_by: 更新来源
        
        Returns:
            新版本号
        """
        version_key = self._get_version_key(entity_type, entity_id)
        new_version = 0
        
        if self._redis:
            try:
                new_version = self._redis.incr(version_key)
            except Exception as e:
                logger.error(f"Redis版本递增失败: {str(e)}")
                new_version = self._local_increment(version_key, updated_by)
        else:
            new_version = self._local_increment(version_key, updated_by)
        
        logger.debug(f"版本递增: {version_key} -> {new_version}")
        return new_version
    
    def _local_increment(self, version_key: str, updated_by: str) -> int:
        """本地版本递增"""
        with self._lock:
            current = self._version_cache.get(version_key)
            current_version = current.version if current else 0
            new_version = current_version + 1
            
            self._version_cache[version_key] = VersionInfo(
                entity_type=version_key.split(self.VERSION_SEPARATOR)[1] if self.VERSION_SEPARATOR in version_key else "unknown",
                entity_id=version_key.split(self.VERSION_SEPARATOR)[2] if version_key.count(self.VERSION_SEPARATOR) >= 2 else "unknown",
                version=new_version,
                updated_at=time.time(),
                updated_by=updated_by,
            )
            
            return new_version
    
    def set_version(
        self,
        entity_type: str,
        entity_id: Any,
        version: int,
        updated_by: str = "system"
    ) -> None:
        """
        设置实体版本号
        
        Args:
            entity_type: 实体类型
            entity_id: 实体ID
            version: 版本号
            updated_by: 更新来源
        """
        version_key = self._get_version_key(entity_type, entity_id)
        
        if self._redis:
            try:
                self._redis.set(version_key, version)
            except Exception as e:
                logger.error(f"设置Redis版本失败: {str(e)}")
        
        with self._lock:
            self._version_cache[version_key] = VersionInfo(
                entity_type=entity_type,
                entity_id=entity_id,
                version=version,
                updated_at=time.time(),
                updated_by=updated_by,
            )
    
    def build_versioned_key(
        self,
        base_key: str,
        entity_type: str,
        entity_id: Any
    ) -> str:
        """
        构建带版本号的缓存键
        
        Args:
            base_key: 基础缓存键
            entity_type: 实体类型
            entity_id: 实体ID
        
        Returns:
            带版本号的缓存键
        """
        version = self.get_version(entity_type, entity_id)
        return f"{base_key}{self.VERSION_SEPARATOR}v{version}"
    
    def is_cache_valid(
        self,
        entity_type: str,
        entity_id: Any,
        cached_version: int
    ) -> bool:
        """
        检查缓存是否有效
        
        Args:
            entity_type: 实体类型
            entity_id: 实体ID
            cached_version: 缓存时的版本号
        
        Returns:
            缓存是否有效
        """
        current_version = self.get_version(entity_type, entity_id)
        return cached_version >= current_version
    
    def batch_increment(
        self,
        entities: List[Dict[str, Any]],
        updated_by: str = "system"
    ) -> Dict[str, int]:
        """
        批量递增版本号
        
        Args:
            entities: 实体列表，每个元素包含 entity_type 和 entity_id
            updated_by: 更新来源
        
        Returns:
            各实体的新版本号
        """
        results = {}
        for entity in entities:
            entity_type = entity.get("entity_type")
            entity_id = entity.get("entity_id")
            if entity_type and entity_id:
                key = f"{entity_type}:{entity_id}"
                results[key] = self.increment_version(entity_type, entity_id, updated_by)
        return results
    
    def get_all_versions(self) -> Dict[str, VersionInfo]:
        """获取所有版本信息"""
        with self._lock:
            return dict(self._version_cache)
    
    def clear_versions(self) -> None:
        """清空所有版本信息"""
        with self._lock:
            self._version_cache.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "total_entities": len(self._version_cache),
                "has_redis": self._redis is not None,
            }


class VersionedCacheWrapper:
    """
    版本感知缓存包装器
    
    自动处理缓存键的版本化，确保缓存一致性
    """
    
    def __init__(
        self,
        cache_manager,
        version_manager: CacheVersionManager,
    ):
        self.cache_manager = cache_manager
        self.version_manager = version_manager
    
    def get(
        self,
        key: str,
        entity_type: str = None,
        entity_id: Any = None,
        loader: Callable = None,
        ttl: int = None,
    ) -> Any:
        """
        获取缓存值（带版本检查）
        
        Args:
            key: 基础缓存键
            entity_type: 实体类型（用于版本控制）
            entity_id: 实体ID（用于版本控制）
            loader: 数据加载函数
            ttl: 过期时间
        """
        if entity_type and entity_id:
            versioned_key = self.version_manager.build_versioned_key(
                key, entity_type, entity_id
            )
        else:
            versioned_key = key
        
        return self.cache_manager.get(versioned_key, loader=loader, ttl=ttl)
    
    def set(
        self,
        key: str,
        value: Any,
        entity_type: str = None,
        entity_id: Any = None,
        ttl: int = None,
    ) -> bool:
        """
        设置缓存值（带版本）
        """
        if entity_type and entity_id:
            versioned_key = self.version_manager.build_versioned_key(
                key, entity_type, entity_id
            )
        else:
            versioned_key = key
        
        return self.cache_manager.set(versioned_key, value, ttl=ttl)
    
    def delete(
        self,
        key: str,
        entity_type: str = None,
        entity_id: Any = None,
    ) -> bool:
        """删除缓存"""
        if entity_type and entity_id:
            versioned_key = self.version_manager.build_versioned_key(
                key, entity_type, entity_id
            )
        else:
            versioned_key = key
        
        return self.cache_manager.delete(versioned_key)
    
    def invalidate_entity(
        self,
        entity_type: str,
        entity_id: Any,
        updated_by: str = "system"
    ) -> int:
        """
        使实体相关的所有缓存失效
        
        通过递增版本号实现
        """
        return self.version_manager.increment_version(
            entity_type, entity_id, updated_by
        )


from typing import Callable
