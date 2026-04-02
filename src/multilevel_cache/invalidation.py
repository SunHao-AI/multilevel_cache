"""
业务失效规则模块 - 实现业务场景的缓存失效规则

提供针对配置系统业务场景的缓存失效规则管理。
"""

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class EntityType(Enum):
    """实体类型"""
    TASK = "task"
    TASK_CLASS = "task_class"
    SERVER = "server"
    CONFIG = "config"
    DEPENDENCY = "dependency"
    USER = "user"


@dataclass
class InvalidationRule:
    """缓存失效规则"""
    name: str
    entity_type: EntityType
    key_patterns: List[str]
    related_patterns: List[str] = field(default_factory=list)
    priority: int = 5
    cascade: bool = True  # 是否级联失效


class CacheInvalidationRules:
    """
    缓存失效规则管理
    
    定义和管理各类业务场景的缓存失效规则
    """
    
    def __init__(self, key_prefix: str = "v1"):
        self.key_prefix = key_prefix
        self._rules: Dict[str, InvalidationRule] = {}
        
        self._init_default_rules()
    
    def _init_default_rules(self) -> None:
        """初始化默认规则"""
        self.register_rule(InvalidationRule(
            name="task_update",
            entity_type=EntityType.TASK,
            key_patterns=[
                "{prefix}:bt:{task_id}",
                "{prefix}:nt:{task_id}",
                "{prefix}:ot:{task_id}",
                "{prefix}:rt:{task_id}",
                "{prefix}:ft:{task_id}",
                "{prefix}:ct:{task_id}",
            ],
            related_patterns=[
                "{prefix}:tl:*",
                "{prefix}:td:{task_id}",
                "{prefix}:dc:{task_id}",
            ],
            priority=5,
            cascade=True,
        ))
        
        self.register_rule(InvalidationRule(
            name="task_class_update",
            entity_type=EntityType.TASK_CLASS,
            key_patterns=[
                "{prefix}:tc:{class_id}",
            ],
            related_patterns=[
                "{prefix}:tl:*",
            ],
            priority=5,
            cascade=True,
        ))
        
        self.register_rule(InvalidationRule(
            name="server_update",
            entity_type=EntityType.SERVER,
            key_patterns=[
                "{prefix}:sn:{server_id}",
                "{prefix}:sc:{server_id}",
            ],
            related_patterns=[
                "{prefix}:pe:{server_id}",
            ],
            priority=5,
            cascade=True,
        ))
        
        self.register_rule(InvalidationRule(
            name="config_update",
            entity_type=EntityType.CONFIG,
            key_patterns=[
                "{prefix}:cfg:{config_id}",
            ],
            related_patterns=[
                "{prefix}:tl:*",
            ],
            priority=5,
            cascade=True,
        ))
        
        self.register_rule(InvalidationRule(
            name="dependency_update",
            entity_type=EntityType.DEPENDENCY,
            key_patterns=[
                "{prefix}:td:{task_id}",
                "{prefix}:dc:{task_id}",
            ],
            related_patterns=[
                "{prefix}:ft:{task_id}",
                "{prefix}:ct:{task_id}",
            ],
            priority=5,
            cascade=True,
        ))
    
    def register_rule(self, rule: InvalidationRule) -> None:
        """注册失效规则"""
        self._rules[rule.name] = rule
        logger.debug(f"注册失效规则: {rule.name}")
    
    def get_keys_to_invalidate(
        self,
        rule_name: str,
        **kwargs
    ) -> Dict[str, List[str]]:
        """
        获取需要失效的缓存键
        
        Args:
            rule_name: 规则名称
            **kwargs: 模板变量（如 task_id, server_id 等）
        
        Returns:
            {
                "keys": ["key1", "key2"],  # 直接失效的键
                "patterns": ["pattern1:*"]  # 需要模式匹配的键
            }
        """
        rule = self._rules.get(rule_name)
        if not rule:
            logger.warning(f"未找到失效规则: {rule_name}")
            return {"keys": [], "patterns": []}
        
        context = {"prefix": self.key_prefix, **kwargs}
        
        keys = []
        for pattern in rule.key_patterns:
            try:
                key = pattern.format(**context)
                keys.append(key)
            except KeyError as e:
                logger.warning(f"模板变量缺失: {e}")
        
        patterns = []
        if rule.cascade:
            for pattern in rule.related_patterns:
                try:
                    p = pattern.format(**context)
                    patterns.append(p)
                except KeyError as e:
                    logger.warning(f"模板变量缺失: {e}")
        
        return {"keys": keys, "patterns": patterns}
    
    def get_task_keys(self, task_id: int, task_type: str = None) -> Dict[str, List[str]]:
        """获取任务相关的缓存键"""
        result = self.get_keys_to_invalidate("task_update", task_id=task_id)
        
        if task_type:
            type_prefix_map = {
                "base": "bt",
                "native": "nt",
                "online": "ot",
                "rule": "rt",
            }
            prefix = type_prefix_map.get(task_type)
            if prefix:
                result["keys"] = [f"{self.key_prefix}:{prefix}:{task_id}"]
        
        return result
    
    def get_server_keys(self, server_id: int) -> Dict[str, List[str]]:
        """获取服务器相关的缓存键"""
        return self.get_keys_to_invalidate("server_update", server_id=server_id)
    
    def get_config_keys(self, config_id: int, config_type: str = None) -> Dict[str, List[str]]:
        """获取配置相关的缓存键"""
        result = self.get_keys_to_invalidate("config_update", config_id=config_id)
        
        if config_type:
            result["keys"].append(f"{self.key_prefix}:cfg:{config_id}:{config_type}")
        
        return result
    
    def get_dependency_keys(self, task_id: int) -> Dict[str, List[str]]:
        """获取依赖关系相关的缓存键"""
        return self.get_keys_to_invalidate("dependency_update", task_id=task_id)


class CacheInvalidationManager:
    """
    缓存失效管理器
    
    统一管理缓存失效操作，支持：
    - 规则驱动的失效
    - MQ通知
    - 版本控制
    """
    
    def __init__(
        self,
        cache_manager,
        rules: CacheInvalidationRules = None,
        sync_manager = None,
        version_manager = None,
    ):
        self.cache_manager = cache_manager
        self.rules = rules or CacheInvalidationRules()
        self.sync_manager = sync_manager
        self.version_manager = version_manager
    
    def invalidate(
        self,
        rule_name: str,
        notify_remote: bool = True,
        increment_version: bool = True,
        **kwargs
    ) -> int:
        """
        执行缓存失效
        
        Args:
            rule_name: 规则名称
            notify_remote: 是否通知远程服务器
            increment_version: 是否递增版本号
            **kwargs: 模板变量
        
        Returns:
            失效的缓存键数量
        """
        keys_info = self.rules.get_keys_to_invalidate(rule_name, **kwargs)
        total_count = 0
        
        for key in keys_info["keys"]:
            self.cache_manager.delete(key)
            total_count += 1
            logger.debug(f"失效缓存键: {key}")
        
        for pattern in keys_info["patterns"]:
            count = self.cache_manager.delete_pattern(pattern)
            total_count += count
            logger.debug(f"失效缓存模式: {pattern}, 数量: {count}")
        
        if increment_version and self.version_manager:
            entity_type = kwargs.get("entity_type", "unknown")
            entity_id = kwargs.get("entity_id") or kwargs.get("task_id") or kwargs.get("server_id")
            if entity_id:
                self.version_manager.increment_version(entity_type, entity_id)
        
        if notify_remote and self.sync_manager:
            self.sync_manager.publish_invalidation(
                cache_keys=keys_info["keys"],
                patterns=keys_info["patterns"],
                config_id=kwargs.get("config_id") or kwargs.get("task_id") or kwargs.get("server_id"),
                config_type=kwargs.get("config_type") or kwargs.get("task_type"),
                source="invalidation_manager",
            )
        
        return total_count
    
    def invalidate_task(
        self,
        task_id: int,
        task_type: str = None,
        notify_remote: bool = True
    ) -> int:
        """使任务相关缓存失效"""
        keys_info = self.rules.get_task_keys(task_id, task_type)
        
        total_count = 0
        for key in keys_info["keys"]:
            self.cache_manager.delete(key)
            total_count += 1
        
        for pattern in keys_info["patterns"]:
            count = self.cache_manager.delete_pattern(pattern)
            total_count += count
        
        if notify_remote and self.sync_manager:
            self.sync_manager.publish_invalidation(
                cache_keys=keys_info["keys"],
                patterns=keys_info["patterns"],
                config_id=task_id,
                config_type=task_type,
                source="task_invalidation",
            )
        
        return total_count
    
    def invalidate_server(
        self,
        server_id: int,
        notify_remote: bool = True
    ) -> int:
        """使服务器相关缓存失效"""
        keys_info = self.rules.get_server_keys(server_id)
        
        total_count = 0
        for key in keys_info["keys"]:
            self.cache_manager.delete(key)
            total_count += 1
        
        for pattern in keys_info["patterns"]:
            count = self.cache_manager.delete_pattern(pattern)
            total_count += count
        
        if notify_remote and self.sync_manager:
            self.sync_manager.publish_invalidation(
                cache_keys=keys_info["keys"],
                patterns=keys_info["patterns"],
                config_id=server_id,
                config_type="server",
                source="server_invalidation",
            )
        
        return total_count
    
    def invalidate_config(
        self,
        config_id: int,
        config_type: str = None,
        notify_remote: bool = True
    ) -> int:
        """使配置相关缓存失效"""
        keys_info = self.rules.get_config_keys(config_id, config_type)
        
        total_count = 0
        for key in keys_info["keys"]:
            self.cache_manager.delete(key)
            total_count += 1
        
        for pattern in keys_info["patterns"]:
            count = self.cache_manager.delete_pattern(pattern)
            total_count += count
        
        if self.version_manager:
            self.version_manager.increment_version("config", config_id)
        
        if notify_remote and self.sync_manager:
            self.sync_manager.publish_invalidation(
                cache_keys=keys_info["keys"],
                patterns=keys_info["patterns"],
                config_id=config_id,
                config_type=config_type,
                source="config_invalidation",
            )
        
        return total_count
    
    def invalidate_by_tags(
        self,
        tags: List[str],
        notify_remote: bool = True
    ) -> int:
        """按标签失效缓存"""
        total_count = 0
        patterns = [f"{self.rules.key_prefix}:*:{tag}:*" for tag in tags]
        
        for pattern in patterns:
            count = self.cache_manager.delete_pattern(pattern)
            total_count += count
        
        if notify_remote and self.sync_manager:
            self.sync_manager.publish_invalidation(
                patterns=patterns,
                source="tag_invalidation",
            )
        
        return total_count


def create_invalidation_decorator(
    invalidation_manager: CacheInvalidationManager
):
    """
    创建缓存失效装饰器工厂
    
    返回一个装饰器工厂函数，用于创建自动失效缓存的装饰器
    """
    
    def invalidate_after_update(
        rule_name: str,
        get_entity_id: Callable = None,
        notify_remote: bool = True,
        **rule_kwargs
    ):
        """
        更新后失效缓存装饰器
        
        Args:
            rule_name: 失效规则名称
            get_entity_id: 从函数参数获取实体ID的函数
            notify_remote: 是否通知远程服务器
            **rule_kwargs: 额外的规则参数
        """
        def decorator(func: Callable) -> Callable:
            from functools import wraps
            
            @wraps(func)
            def wrapper(*args, **kwargs):
                result = func(*args, **kwargs)
                
                entity_id = None
                if get_entity_id:
                    entity_id = get_entity_id(*args, **kwargs)
                elif 'task_id' in kwargs:
                    entity_id = kwargs['task_id']
                elif 'server_id' in kwargs:
                    entity_id = kwargs['server_id']
                elif 'config_id' in kwargs:
                    entity_id = kwargs['config_id']
                elif len(args) > 1:
                    entity_id = args[1] if isinstance(args[1], int) else None
                
                if entity_id:
                    invalidation_manager.invalidate(
                        rule_name,
                        notify_remote=notify_remote,
                        entity_id=entity_id,
                        **rule_kwargs
                    )
                
                return result
            
            return wrapper
        
        return decorator
    
    return invalidate_after_update
