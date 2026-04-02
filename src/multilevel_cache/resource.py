"""
资源监控模块 - 实现缓存系统资源监控和限制

监控系统资源使用情况，防止缓存占用过多资源。
"""

import gc
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ResourceLimits:
    """资源限制配置"""
    max_memory_mb: int = 512          # 最大内存使用（MB）
    max_cpu_percent: float = 80.0     # 最大CPU使用率
    max_cache_size: int = 10000       # 最大缓存条目数
    max_key_length: int = 1024        # 最大键长度
    max_value_size_mb: int = 10       # 最大值大小（MB）
    
    warning_threshold: float = 0.8    # 警告阈值（80%）
    critical_threshold: float = 0.95  # 临界阈值（95%）


@dataclass
class ResourceUsage:
    """资源使用情况"""
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    cpu_percent: float = 0.0
    cache_size: int = 0
    cache_hit_rate: float = 0.0
    timestamp: float = field(default_factory=time.time)


class ResourceMonitor:
    """
    资源监控器
    
    监控缓存系统的资源使用情况，支持：
    - 内存使用监控
    - CPU使用监控
    - 缓存大小监控
    - 阈值告警
    """
    
    def __init__(
        self,
        limits: ResourceLimits = None,
        alert_callback: Callable = None,
    ):
        self.limits = limits or ResourceLimits()
        self.alert_callback = alert_callback
        
        self._usage_history: List[ResourceUsage] = []
        self._max_history_size = 100
        self._lock = threading.Lock()
        
        self._monitoring = False
        self._monitor_thread = None
        self._monitor_interval = 10
        
        self._alerts: List[Dict[str, Any]] = []
    
    def get_current_usage(self) -> ResourceUsage:
        """获取当前资源使用情况"""
        usage = ResourceUsage()
        
        try:
            import psutil
            process = psutil.Process(os.getpid())
            
            usage.memory_mb = process.memory_info().rss / 1024 / 1024
            usage.memory_percent = process.memory_percent()
            usage.cpu_percent = process.cpu_percent(interval=0.1)
            
        except ImportError:
            usage.memory_mb = self._estimate_memory_usage()
            usage.cpu_percent = 0.0
        
        return usage
    
    def _estimate_memory_usage(self) -> float:
        """估算内存使用（无psutil时）"""
        try:
            import tracemalloc
            if tracemalloc.is_tracing():
                current, peak = tracemalloc.get_traced_memory()
                return current / 1024 / 1024
        except ImportError:
            pass
        
        return sys.getsizeof({}) / 1024 / 1024
    
    def check_limits(self, cache_size: int = 0) -> Dict[str, Any]:
        """
        检查资源限制
        
        Args:
            cache_size: 当前缓存大小
        
        Returns:
            检查结果
        """
        usage = self.get_current_usage()
        usage.cache_size = cache_size
        
        result = {
            "within_limits": True,
            "warnings": [],
            "errors": [],
            "usage": usage,
        }
        
        if usage.memory_mb > self.limits.max_memory_mb * self.limits.critical_threshold:
            result["within_limits"] = False
            result["errors"].append(f"内存使用超过临界阈值: {usage.memory_mb:.1f}MB")
            self._trigger_alert("critical", "memory", usage.memory_mb)
        
        elif usage.memory_mb > self.limits.max_memory_mb * self.limits.warning_threshold:
            result["warnings"].append(f"内存使用接近限制: {usage.memory_mb:.1f}MB")
            self._trigger_alert("warning", "memory", usage.memory_mb)
        
        if cache_size > self.limits.max_cache_size * self.limits.critical_threshold:
            result["within_limits"] = False
            result["errors"].append(f"缓存大小超过临界阈值: {cache_size}")
            self._trigger_alert("critical", "cache_size", cache_size)
        
        elif cache_size > self.limits.max_cache_size * self.limits.warning_threshold:
            result["warnings"].append(f"缓存大小接近限制: {cache_size}")
            self._trigger_alert("warning", "cache_size", cache_size)
        
        with self._lock:
            self._usage_history.append(usage)
            if len(self._usage_history) > self._max_history_size:
                self._usage_history = self._usage_history[-self._max_history_size:]
        
        return result
    
    def should_evict(self, cache_size: int) -> bool:
        """判断是否需要执行淘汰"""
        usage = self.get_current_usage()
        
        if usage.memory_mb > self.limits.max_memory_mb * self.limits.critical_threshold:
            return True
        
        if cache_size > self.limits.max_cache_size:
            return True
        
        return False
    
    def get_eviction_count(self, cache_size: int) -> int:
        """计算需要淘汰的条目数量"""
        usage = self.get_current_usage()
        
        if usage.memory_mb > self.limits.max_memory_mb * self.limits.warning_threshold:
            target_size = int(cache_size * 0.7)
            return max(0, cache_size - target_size)
        
        if cache_size > self.limits.max_cache_size * self.limits.warning_threshold:
            return int(cache_size * 0.2)
        
        return 0
    
    def _trigger_alert(self, level: str, resource: str, value: Any) -> None:
        """触发告警"""
        alert = {
            "level": level,
            "resource": resource,
            "value": value,
            "limit": getattr(self.limits, f"max_{resource}", None) or getattr(self.limits, f"max_{resource}_mb", None),
            "timestamp": time.time(),
        }
        
        self._alerts.append(alert)
        
        if self.alert_callback:
            try:
                self.alert_callback(alert)
            except Exception as e:
                logger.error(f"告警回调执行失败: {str(e)}")
        
        logger.warning(f"资源告警 [{level}] {resource}: {value}")
    
    def start_monitoring(self, interval: int = 10) -> None:
        """启动后台监控"""
        self._monitor_interval = interval
        self._monitoring = True
        
        def monitor_loop():
            while self._monitoring:
                try:
                    self.check_limits(0)
                except Exception as e:
                    logger.error(f"监控循环错误: {str(e)}")
                
                time.sleep(self._monitor_interval)
        
        self._monitor_thread = threading.Thread(target=monitor_loop, daemon=True)
        self._monitor_thread.start()
        
        logger.info(f"资源监控已启动，间隔: {interval}秒")
    
    def stop_monitoring(self) -> None:
        """停止后台监控"""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        
        logger.info("资源监控已停止")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            if not self._usage_history:
                return {"no_data": True}
            
            recent = self._usage_history[-10:]
            avg_memory = sum(u.memory_mb for u in recent) / len(recent)
            avg_cpu = sum(u.cpu_percent for u in recent) / len(recent)
            
            return {
                "current": self._usage_history[-1].__dict__ if self._usage_history else None,
                "avg_memory_mb": avg_memory,
                "avg_cpu_percent": avg_cpu,
                "limits": {
                    "max_memory_mb": self.limits.max_memory_mb,
                    "max_cache_size": self.limits.max_cache_size,
                },
                "alert_count": len(self._alerts),
                "recent_alerts": self._alerts[-5:],
            }
    
    def get_history(self, count: int = 20) -> List[Dict[str, Any]]:
        """获取历史记录"""
        with self._lock:
            return [u.__dict__ for u in self._usage_history[-count:]]


class ResourceAwareCache:
    """
    资源感知缓存包装器
    
    在缓存操作前检查资源限制，自动执行淘汰
    """
    
    def __init__(
        self,
        cache_backend,
        resource_monitor: ResourceMonitor = None,
        limits: ResourceLimits = None,
    ):
        self._cache = cache_backend
        self._monitor = resource_monitor or ResourceMonitor(limits)
        self._limits = limits or ResourceLimits()
    
    def get(self, key: str) -> Any:
        """获取缓存值"""
        self._check_key_length(key)
        return self._cache.get(key)
    
    def set(self, key: str, value: Any, ttl: int = None) -> bool:
        """设置缓存值"""
        self._check_key_length(key)
        self._check_value_size(value)
        
        stats = self._cache.get_stats() if hasattr(self._cache, 'get_stats') else {}
        cache_size = stats.get('size', 0)
        
        if self._monitor.should_evict(cache_size + 1):
            eviction_count = self._monitor.get_eviction_count(cache_size)
            self._evict(eviction_count)
        
        return self._cache.set(key, value, ttl)
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        return self._cache.delete(key)
    
    def _check_key_length(self, key: str) -> None:
        """检查键长度"""
        if len(key) > self._limits.max_key_length:
            raise ValueError(f"缓存键长度超过限制: {len(key)} > {self._limits.max_key_length}")
    
    def _check_value_size(self, value: Any) -> None:
        """检查值大小"""
        try:
            import sys
            size = sys.getsizeof(value)
            if size > self._limits.max_value_size_mb * 1024 * 1024:
                raise ValueError(f"缓存值大小超过限制: {size / 1024 / 1024:.2f}MB")
        except Exception:
            pass
    
    def _evict(self, count: int) -> None:
        """执行淘汰"""
        if hasattr(self._cache, '_evict'):
            for _ in range(count):
                self._cache._evict()
        elif hasattr(self._cache, 'clear'):
            logger.warning("缓存后端不支持选择性淘汰，执行清空操作")
            self._cache.clear()
    
    def get_resource_stats(self) -> Dict[str, Any]:
        """获取资源统计"""
        return self._monitor.get_stats()
