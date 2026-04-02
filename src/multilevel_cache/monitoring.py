"""
缓存监控模块 - 提供性能监控和统计功能
"""

import json
import logging
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class CacheMetrics:
    """
    缓存性能指标
    
    记录各级缓存的命中/未命中次数、延迟等
    """
    l1_hits: int = 0
    l1_misses: int = 0
    l2_hits: int = 0
    l2_misses: int = 0
    l3_hits: int = 0
    l3_misses: int = 0
    total_requests: int = 0
    total_errors: int = 0
    
    l1_latency_total: float = 0.0
    l2_latency_total: float = 0.0
    l3_latency_total: float = 0.0
    
    evictions: int = 0
    memory_usage: int = 0
    
    _start_time: float = field(default_factory=time.time)
    
    @property
    def l1_hit_rate(self) -> float:
        total = self.l1_hits + self.l1_misses
        return (self.l1_hits / total * 100) if total > 0 else 0.0
    
    @property
    def l2_hit_rate(self) -> float:
        total = self.l2_hits + self.l2_misses
        return (self.l2_hits / total * 100) if total > 0 else 0.0
    
    @property
    def overall_hit_rate(self) -> float:
        total_hits = self.l1_hits + self.l2_hits + self.l3_hits
        return (total_hits / self.total_requests * 100) if self.total_requests > 0 else 0.0
    
    @property
    def avg_l1_latency(self) -> float:
        return (self.l1_latency_total / (self.l1_hits + self.l1_misses)) if (self.l1_hits + self.l1_misses) > 0 else 0.0
    
    @property
    def avg_l2_latency(self) -> float:
        return (self.l2_latency_total / (self.l2_hits + self.l2_misses)) if (self.l2_hits + self.l2_misses) > 0 else 0.0
    
    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._start_time
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "l1_hits": self.l1_hits,
            "l1_misses": self.l1_misses,
            "l1_hit_rate": f"{self.l1_hit_rate:.2f}%",
            "l1_avg_latency_ms": f"{self.avg_l1_latency * 1000:.2f}",
            "l2_hits": self.l2_hits,
            "l2_misses": self.l2_misses,
            "l2_hit_rate": f"{self.l2_hit_rate:.2f}%",
            "l2_avg_latency_ms": f"{self.avg_l2_latency * 1000:.2f}",
            "l3_hits": self.l3_hits,
            "l3_misses": self.l3_misses,
            "total_requests": self.total_requests,
            "overall_hit_rate": f"{self.overall_hit_rate:.2f}%",
            "total_errors": self.total_errors,
            "evictions": self.evictions,
            "uptime_seconds": f"{self.uptime_seconds:.0f}",
        }
    
    def to_json(self) -> str:
        """转换为JSON"""
        return json.dumps(self.to_dict(), indent=2)


class CacheMonitor:
    """
    缓存监控器
    
    提供实时监控、告警、统计功能
    """
    
    def __init__(
        self,
        alert_threshold_hit_rate: float = 50.0,
        alert_threshold_error_rate: float = 10.0,
        alert_threshold_latency_ms: float = 100.0,
    ):
        self.metrics = CacheMetrics()
        self.alert_threshold_hit_rate = alert_threshold_hit_rate
        self.alert_threshold_error_rate = alert_threshold_error_rate
        self.alert_threshold_latency_ms = alert_threshold_latency_ms
        
        self._alerts: List[Dict[str, Any]] = []
        self._alert_callbacks: List[Callable] = []
        self._lock = threading.Lock()
        
        self._operation_times: Dict[str, List[float]] = defaultdict(list)
        self._error_counts: Dict[str, int] = defaultdict(int)
    
    def record_hit(self, level: str, latency: float = 0.0) -> None:
        """记录命中"""
        with self._lock:
            self.metrics.total_requests += 1
            
            if level == "l1":
                self.metrics.l1_hits += 1
                self.metrics.l1_latency_total += latency
            elif level == "l2":
                self.metrics.l2_hits += 1
                self.metrics.l2_latency_total += latency
            elif level == "l3":
                self.metrics.l3_hits += 1
                self.metrics.l3_latency_total += latency
    
    def record_miss(self, level: str, latency: float = 0.0) -> None:
        """记录未命中"""
        with self._lock:
            self.metrics.total_requests += 1
            
            if level == "l1":
                self.metrics.l1_misses += 1
                self.metrics.l1_latency_total += latency
            elif level == "l2":
                self.metrics.l2_misses += 1
                self.metrics.l2_latency_total += latency
            elif level == "l3":
                self.metrics.l3_misses += 1
                self.metrics.l3_latency_total += latency
    
    def record_error(self, error_type: str = "unknown") -> None:
        """记录错误"""
        with self._lock:
            self.metrics.total_errors += 1
            self._error_counts[error_type] += 1
            
            self._check_alerts()
    
    def record_eviction(self, count: int = 1) -> None:
        """记录淘汰"""
        with self._lock:
            self.metrics.evictions += count
    
    def record_operation(self, operation: str, duration: float) -> None:
        """记录操作耗时"""
        with self._lock:
            self._operation_times[operation].append(duration)
            
            if len(self._operation_times[operation]) > 1000:
                self._operation_times[operation] = self._operation_times[operation][-500:]
    
    def add_alert_callback(self, callback: Callable) -> None:
        """添加告警回调"""
        self._alert_callbacks.append(callback)
    
    def _check_alerts(self) -> None:
        """检查告警条件"""
        alerts = []
        
        if self.metrics.overall_hit_rate < self.alert_threshold_hit_rate:
            alerts.append({
                "type": "low_hit_rate",
                "message": f"缓存命中率过低: {self.metrics.overall_hit_rate:.2f}%",
                "threshold": self.alert_threshold_hit_rate,
                "current": self.metrics.overall_hit_rate,
                "timestamp": datetime.now().isoformat(),
            })
        
        error_rate = (self.metrics.total_errors / self.metrics.total_requests * 100) if self.metrics.total_requests > 0 else 0
        if error_rate > self.alert_threshold_error_rate:
            alerts.append({
                "type": "high_error_rate",
                "message": f"错误率过高: {error_rate:.2f}%",
                "threshold": self.alert_threshold_error_rate,
                "current": error_rate,
                "timestamp": datetime.now().isoformat(),
            })
        
        avg_latency = (self.metrics.l1_latency_total + self.metrics.l2_latency_total) / max(1, self.metrics.total_requests) * 1000
        if avg_latency > self.alert_threshold_latency_ms:
            alerts.append({
                "type": "high_latency",
                "message": f"平均延迟过高: {avg_latency:.2f}ms",
                "threshold": self.alert_threshold_latency_ms,
                "current": avg_latency,
                "timestamp": datetime.now().isoformat(),
            })
        
        for alert in alerts:
            self._alerts.append(alert)
            self._trigger_alert(alert)
    
    def _trigger_alert(self, alert: Dict[str, Any]) -> None:
        """触发告警"""
        logger.warning(f"缓存告警: {alert['message']}")
        
        for callback in self._alert_callbacks:
            try:
                callback(alert)
            except Exception as e:
                logger.error(f"告警回调执行失败: {str(e)}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            stats = self.metrics.to_dict()
            
            stats["operation_stats"] = {
                op: {
                    "count": len(times),
                    "avg_ms": (sum(times) / len(times) * 1000) if times else 0,
                    "max_ms": max(times) * 1000 if times else 0,
                    "min_ms": min(times) * 1000 if times else 0,
                }
                for op, times in self._operation_times.items()
            }
            
            stats["error_breakdown"] = dict(self._error_counts)
            stats["recent_alerts"] = self._alerts[-10:]
            
            return stats
    
    def get_metrics(self) -> CacheMetrics:
        """获取指标对象"""
        return self.metrics
    
    def reset(self) -> None:
        """重置统计"""
        with self._lock:
            self.metrics = CacheMetrics()
            self._alerts.clear()
            self._operation_times.clear()
            self._error_counts.clear()
    
    def export_prometheus(self) -> str:
        """导出Prometheus格式指标"""
        lines = []
        
        lines.append("# HELP cache_requests_total Total cache requests")
        lines.append("# TYPE cache_requests_total counter")
        lines.append(f"cache_requests_total {self.metrics.total_requests}")
        
        lines.append("# HELP cache_hits_total Cache hits by level")
        lines.append("# TYPE cache_hits_total counter")
        lines.append(f"cache_hits_total{{level=\"l1\"}} {self.metrics.l1_hits}")
        lines.append(f"cache_hits_total{{level=\"l2\"}} {self.metrics.l2_hits}")
        lines.append(f"cache_hits_total{{level=\"l3\"}} {self.metrics.l3_hits}")
        
        lines.append("# HELP cache_misses_total Cache misses by level")
        lines.append("# TYPE cache_misses_total counter")
        lines.append(f"cache_misses_total{{level=\"l1\"}} {self.metrics.l1_misses}")
        lines.append(f"cache_misses_total{{level=\"l2\"}} {self.metrics.l2_misses}")
        lines.append(f"cache_misses_total{{level=\"l3\"}} {self.metrics.l3_misses}")
        
        lines.append("# HELP cache_hit_rate Cache hit rate percentage")
        lines.append("# TYPE cache_hit_rate gauge")
        lines.append(f"cache_hit_rate {self.metrics.overall_hit_rate}")
        
        lines.append("# HELP cache_errors_total Total cache errors")
        lines.append("# TYPE cache_errors_total counter")
        lines.append(f"cache_errors_total {self.metrics.total_errors}")
        
        lines.append("# HELP cache_evictions_total Total cache evictions")
        lines.append("# TYPE cache_evictions_total counter")
        lines.append(f"cache_evictions_total {self.metrics.evictions}")
        
        return "\n".join(lines)


class PerformanceTracker:
    """
    性能追踪器
    
    用于追踪单个操作的性能
    """
    
    def __init__(self, monitor: Optional[CacheMonitor] = None):
        self.monitor = monitor
        self._start_time: Optional[float] = None
        self._operation: Optional[str] = None
    
    def start(self, operation: str) -> "PerformanceTracker":
        """开始追踪"""
        self._operation = operation
        self._start_time = time.time()
        return self
    
    def end(self) -> float:
        """结束追踪"""
        if self._start_time is None:
            return 0.0
        
        duration = time.time() - self._start_time
        
        if self.monitor and self._operation:
            self.monitor.record_operation(self._operation, duration)
        
        self._start_time = None
        self._operation = None
        
        return duration
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.end()


def track_performance(monitor: Optional[CacheMonitor] = None):
    """
    性能追踪装饰器
    
    Example:
        @track_performance(monitor)
        def expensive_operation():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            tracker = PerformanceTracker(monitor)
            tracker.start(func.__name__)
            try:
                return func(*args, **kwargs)
            finally:
                tracker.end()
        
        return wrapper
    
    return decorator


import functools
