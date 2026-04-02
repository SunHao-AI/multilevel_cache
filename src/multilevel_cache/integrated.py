"""
集成缓存管理器 - 统一管理所有缓存功能

整合多级缓存、MQ同步、版本控制、失效规则、资源监控等功能。
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class IntegratedCacheConfig:
    """集成缓存配置"""
    name: str = "integrated_cache"
    
    # 基础缓存配置
    l1_max_size: int = 1000
    l1_ttl: int = 300
    l2_ttl: int = 1800
    
    # MQ同步配置
    enable_mq_sync: bool = True
    mq_host: str = "localhost"
    mq_port: int = 5672
    mq_user: str = "guest"
    mq_password: str = "guest"
    mq_exchange: str = "cache_sync"
    
    # Redis配置
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    
    # 资源限制
    max_memory_mb: int = 512
    max_cache_size: int = 10000
    
    # 监控配置
    enable_monitoring: bool = True
    monitor_interval: int = 10
    
    # 版本控制
    enable_version_control: bool = True


class IntegratedCacheManager:
    """
    集成缓存管理器
    
    统一管理所有缓存功能，提供一站式缓存解决方案。
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, config: IntegratedCacheConfig = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, config: IntegratedCacheConfig = None):
        if hasattr(self, '_initialized') and self._initialized:
            return
        
        self.config = config or IntegratedCacheConfig()
        
        self._cache_manager = None
        self._sync_manager = None
        self._version_manager = None
        self._invalidation_manager = None
        self._resource_monitor = None
        
        self._init_components()
        self._initialized = True
    
    def _init_components(self) -> None:
        """初始化各组件"""
        from .core import CacheManager, CacheConfig, MemoryCacheConfig, RedisConfig, TTLConfig, DegradationConfig
        from .sync import CacheSyncManager, MQConfig
        from .version import CacheVersionManager
        from .invalidation import CacheInvalidationRules, CacheInvalidationManager
        from .resource import ResourceMonitor, ResourceLimits
        
        cache_config = CacheConfig(
            name=self.config.name,
            memory_config=MemoryCacheConfig(
                max_size=self.config.l1_max_size,
                default_ttl=self.config.l1_ttl,
            ),
            redis_config=RedisConfig(
                host=self.config.redis_host,
                port=self.config.redis_port,
                db=self.config.redis_db,
            ),
            ttl_config=TTLConfig(
                l1_ttl=self.config.l1_ttl,
                l2_ttl=self.config.l2_ttl,
            ),
            degradation_config=DegradationConfig(
                enable_l2_fallback=True,
                failure_threshold=3,
            ),
        )
        
        self._cache_manager = CacheManager(cache_config)
        
        if self.config.enable_mq_sync:
            mq_config = MQConfig(
                host=self.config.mq_host,
                port=self.config.mq_port,
                user=self.config.mq_user,
                password=self.config.mq_password,
                exchange=self.config.mq_exchange,
            )
            
            self._sync_manager = CacheSyncManager(
                mq_config=mq_config,
                cache_manager=self._cache_manager,
                enable_sync=True,
            )
        
        if self.config.enable_version_control:
            self._version_manager = CacheVersionManager()
        
        rules = CacheInvalidationRules()
        self._invalidation_manager = CacheInvalidationManager(
            cache_manager=self._cache_manager,
            rules=rules,
            sync_manager=self._sync_manager,
            version_manager=self._version_manager,
        )
        
        if self.config.enable_monitoring:
            limits = ResourceLimits(
                max_memory_mb=self.config.max_memory_mb,
                max_cache_size=self.config.max_cache_size,
            )
            self._resource_monitor = ResourceMonitor(limits=limits)
        
        logger.info("集成缓存管理器初始化完成")
    
    # ==================== 基础缓存操作 ====================
    
    def get(
        self,
        key: str,
        loader: Callable = None,
        ttl: int = None,
        entity_type: str = None,
        entity_id: Any = None,
    ) -> Any:
        """
        获取缓存值
        
        Args:
            key: 缓存键
            loader: 数据加载函数
            ttl: 过期时间
            entity_type: 实体类型（版本控制）
            entity_id: 实体ID（版本控制）
        """
        if entity_type and entity_id and self._version_manager:
            version = self._version_manager.get_version(entity_type, entity_id)
            versioned_key = f"{key}:v{version}"
            return self._cache_manager.get(versioned_key, loader, ttl)
        
        return self._cache_manager.get(key, loader, ttl)
    
    def set(
        self,
        key: str,
        value: Any,
        ttl: int = None,
        entity_type: str = None,
        entity_id: Any = None,
        notify_remote: bool = False,
    ) -> bool:
        """
        设置缓存值
        
        Args:
            key: 缓存键
            value: 缓存值
            ttl: 过期时间
            entity_type: 实体类型
            entity_id: 实体ID
            notify_remote: 是否通知远程服务器
        """
        cache_key = key
        
        if entity_type and entity_id and self._version_manager:
            version = self._version_manager.get_version(entity_type, entity_id)
            cache_key = f"{key}:v{version}"
        
        result = self._cache_manager.set(cache_key, value, ttl)
        
        if notify_remote and self._sync_manager:
            self._sync_manager.publish_invalidation(
                cache_keys=[cache_key],
                config_type=entity_type,
                config_id=entity_id if isinstance(entity_id, int) else None,
            )
        
        return result
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        return self._cache_manager.delete(key)
    
    def delete_pattern(self, pattern: str) -> int:
        """按模式删除缓存"""
        return self._cache_manager.delete_pattern(pattern)
    
    def clear(self) -> None:
        """清空缓存"""
        self._cache_manager.clear()
    
    # ==================== 业务失效操作 ====================
    
    def invalidate_task(
        self,
        task_id: int,
        task_type: str = None,
        notify_remote: bool = True
    ) -> int:
        """使任务相关缓存失效"""
        if self._invalidation_manager:
            return self._invalidation_manager.invalidate_task(
                task_id, task_type, notify_remote
            )
        
        patterns = [
            f"v1:bt:{task_id}",
            f"v1:nt:{task_id}",
            f"v1:ot:{task_id}",
            f"v1:tl:*",
        ]
        count = 0
        for p in patterns:
            count += self.delete_pattern(p)
        return count
    
    def invalidate_server(
        self,
        server_id: int,
        notify_remote: bool = True
    ) -> int:
        """使服务器相关缓存失效"""
        if self._invalidation_manager:
            return self._invalidation_manager.invalidate_server(
                server_id, notify_remote
            )
        
        patterns = [f"v1:sn:{server_id}", f"v1:sc:{server_id}"]
        count = 0
        for p in patterns:
            count += self.delete_pattern(p)
        return count
    
    def invalidate_config(
        self,
        config_id: int,
        config_type: str = None,
        notify_remote: bool = True
    ) -> int:
        """使配置相关缓存失效"""
        if self._invalidation_manager:
            return self._invalidation_manager.invalidate_config(
                config_id, config_type, notify_remote
            )
        
        if self._version_manager:
            self._version_manager.increment_version("config", config_id)
        
        return self.delete_pattern(f"v1:cfg:{config_id}*")
    
    # ==================== 版本控制操作 ====================
    
    def get_version(self, entity_type: str, entity_id: Any) -> int:
        """获取实体版本号"""
        if self._version_manager:
            return self._version_manager.get_version(entity_type, entity_id)
        return 0
    
    def increment_version(
        self,
        entity_type: str,
        entity_id: Any,
        updated_by: str = "system"
    ) -> int:
        """递增实体版本号"""
        if self._version_manager:
            return self._version_manager.increment_version(
                entity_type, entity_id, updated_by
            )
        return 0
    
    # ==================== MQ同步操作 ====================
    
    def start_sync(self) -> bool:
        """启动MQ同步"""
        if self._sync_manager:
            return self._sync_manager.start_consumer()
        return False
    
    def stop_sync(self) -> None:
        """停止MQ同步"""
        if self._sync_manager:
            self._sync_manager.stop_consumer()
    
    def publish_invalidation(
        self,
        cache_keys: List[str] = None,
        patterns: List[str] = None,
        config_id: int = None,
        config_type: str = None,
    ) -> bool:
        """发布缓存失效消息"""
        if self._sync_manager:
            return self._sync_manager.publish_invalidation(
                cache_keys=cache_keys,
                patterns=patterns,
                config_id=config_id,
                config_type=config_type,
            )
        return False
    
    # ==================== 资源监控操作 ====================
    
    def start_monitoring(self) -> None:
        """启动资源监控"""
        if self._resource_monitor:
            self._resource_monitor.start_monitoring(
                interval=self.config.monitor_interval
            )
    
    def stop_monitoring(self) -> None:
        """停止资源监控"""
        if self._resource_monitor:
            self._resource_monitor.stop_monitoring()
    
    def get_resource_stats(self) -> Dict[str, Any]:
        """获取资源统计"""
        if self._resource_monitor:
            return self._resource_monitor.get_stats()
        return {}
    
    # ==================== 状态查询 ====================
    
    def get_stats(self) -> Dict[str, Any]:
        """获取完整统计信息"""
        stats = {
            "cache": self._cache_manager.get_stats() if self._cache_manager else None,
            "sync": self._sync_manager.get_status() if self._sync_manager else None,
            "version": self._version_manager.get_stats() if self._version_manager else None,
            "resource": self.get_resource_stats(),
        }
        return stats
    
    def is_healthy(self) -> bool:
        """检查缓存系统是否健康"""
        if not self._cache_manager:
            return False
        
        stats = self._cache_manager.get_stats()
        if not stats.get("enabled", True):
            return False
        
        if self._resource_monitor:
            usage = self._resource_monitor.get_current_usage()
            if usage.memory_mb > self.config.max_memory_mb * 0.95:
                return False
        
        return True
    
    def get_degradation_status(self) -> Dict[str, Any]:
        """获取降级状态"""
        return {
            "cache_enabled": self._cache_manager.is_enabled() if self._cache_manager else False,
            "mq_available": self._sync_manager.is_available if self._sync_manager else False,
            "is_healthy": self.is_healthy(),
        }
    
    # ==================== 生命周期管理 ====================
    
    def start(self) -> None:
        """启动缓存管理器"""
        self.start_sync()
        self.start_monitoring()
        logger.info("集成缓存管理器已启动")
    
    def shutdown(self) -> None:
        """关闭缓存管理器"""
        self.stop_monitoring()
        self.stop_sync()
        
        if self._sync_manager:
            self._sync_manager.close()
        
        logger.info("集成缓存管理器已关闭")
    
    @classmethod
    def get_instance(cls) -> "IntegratedCacheManager":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """重置单例实例"""
        if cls._instance:
            cls._instance.shutdown()
            cls._instance = None


def create_cache_manager(
    config: IntegratedCacheConfig = None,
    auto_start: bool = True,
) -> IntegratedCacheManager:
    """
    创建缓存管理器实例
    
    Args:
        config: 配置对象
        auto_start: 是否自动启动
    
    Returns:
        IntegratedCacheManager实例
    """
    manager = IntegratedCacheManager(config)
    
    if auto_start:
        manager.start()
    
    return manager
