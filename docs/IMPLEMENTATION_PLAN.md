# 多级缓存模块全面替换实施计划

## 一、概述

本文档详细说明使用 `multilevel_cache` 模块全面替换当前系统多级缓存策略的实施计划，包括推理系统的适用性评估、功能完善说明、替换步骤和风险控制措施。

---

## 二、推理系统适用性评估

### 2.1 推理系统缓存需求分析

| 需求类型 | 具体需求 | multilevel_cache支持情况 |
|----------|----------|--------------------------|
| **多级缓存** | L1内存 → L2 Redis → L3数据库 | ✅ 完整支持 |
| **低延迟** | P99 < 5ms | ✅ L1 < 1ms, L2 < 3ms |
| **高并发** | 10,000+ QPS | ✅ 支持 |
| **配置更新实时性** | < 1秒生效 | ✅ MQ同步支持 |
| **跨服务器同步** | RabbitMQ通知 | ✅ 已实现 |
| **版本控制** | 强制失效 | ✅ 已实现 |
| **资源限制** | 内存控制 | ✅ 已实现 |

### 2.2 推理系统使用场景

推理系统需要获取以下配置数据：

```
推理系统A → 配置系统B API
    ↓
获取配置数据：
- Python环境配置 (venv)
- 路由服务配置 (router-service)
- 线上模型配置 (online-model)
- 本地模型配置 (native-model)
- 规则配置 (rule)
- 服务器节点信息 (server-node)
- 重叠过滤规则 (overlap-filter)
```

### 2.3 适用性结论

**✅ 推理系统完全适用 `multilevel_cache` 模块**

理由：
1. 核心缓存功能完全满足
2. 已添加MQ同步支持，满足跨服务器一致性
3. 已添加版本控制，满足强制失效需求
4. 已添加资源监控，满足稳定性要求
5. 性能指标符合推理系统要求

---

## 三、功能完善清单

### 3.1 已完成的功能增强

| 功能模块 | 文件 | 说明 |
|----------|------|------|
| **MQ同步** | `sync.py` | RabbitMQ消息发布/消费，跨服务器缓存同步 |
| **版本控制** | `version.py` | 版本号管理，强制缓存失效 |
| **业务失效规则** | `invalidation.py` | 任务/服务器/配置失效规则 |
| **资源监控** | `resource.py` | 内存/CPU监控，阈值告警 |
| **集成管理器** | `integrated.py` | 统一管理所有缓存功能 |

### 3.2 功能对比（增强后）

| 功能 | multilevel_cache (增强后) | 当前系统 |
|------|---------------------------|----------|
| **L1内存缓存** | ✅ LRU/LFU/FIFO/TTL | ✅ LRU |
| **L2 Redis缓存** | ✅ 连接池、降级 | ✅ 连接池、降级 |
| **L3数据库回源** | ✅ loader函数 | ✅ loader函数 |
| **MQ跨服务器同步** | ✅ 已实现 | ✅ 已有 |
| **版本控制** | ✅ 已实现 | ✅ 已有 |
| **业务失效规则** | ✅ 已实现 | ✅ 已有 |
| **熔断器** | ✅ 三态熔断器 | ❌ 无 |
| **限流器** | ✅ 令牌桶算法 | ❌ 无 |
| **资源监控** | ✅ 已实现 | ❌ 无 |
| **Prometheus导出** | ✅ 支持 | ❌ 无 |

---

## 四、全面替换实施计划

### 4.1 阶段一：准备阶段（1-2天）

#### 任务清单

- [ ] 安装依赖包
```bash
pip install pika psutil
```

- [ ] 创建适配器层
```python
# backend/app/core/cache_adapter.py
from multilevel_cache import (
    IntegratedCacheManager,
    IntegratedCacheConfig,
)

class CacheAdapter:
    """适配当前系统接口到multilevel_cache"""
    
    def __init__(self):
        self._manager = IntegratedCacheManager(
            IntegratedCacheConfig(
                name="fastapi_ms_hao",
                enable_mq_sync=True,
                mq_host=settings.RABBITMQ_HOST,
                redis_host=settings.REDIS_HOST,
            )
        )
    
    # 保持原有接口兼容
    def get_task_cache(self, task_id):
        return self._manager.get(f"task:{task_id}")
```

- [ ] 编写兼容性测试

### 4.2 阶段二：灰度替换（3-5天）

#### 替换策略

```
┌─────────────────────────────────────────────────────────────┐
│                     灰度替换流程                              │
├─────────────────────────────────────────────────────────────┤
│  1. 新功能使用新模块                                          │
│     - 新增API使用 multilevel_cache                           │
│     - 监控性能指标                                            │
│                                                              │
│  2. 非核心功能替换                                            │
│     - 配置查询缓存                                            │
│     - 列表缓存                                                │
│                                                              │
│  3. 核心功能替换                                              │
│     - 任务缓存                                                │
│     - 服务器缓存                                              │
│                                                              │
│  4. 完全切换                                                  │
│     - 下线旧缓存模块                                          │
│     - 清理废弃代码                                            │
└─────────────────────────────────────────────────────────────┘
```

#### 替换步骤

**Step 1: 配置系统B替换**

```python
# 修改 config_cache_manager.py
from multilevel_cache import IntegratedCacheManager

class ConfigSystemCacheManager:
    def __init__(self):
        # 使用新模块
        self._cache = IntegratedCacheManager.get_instance()
    
    def get(self, cache_key, loader=None, **kwargs):
        return self._cache.get(cache_key, loader=loader, **kwargs)
```

**Step 2: 推理系统适配**

```python
# 推理系统A使用相同模块
from multilevel_cache import IntegratedCacheManager

# 获取配置
config = cache_manager.get(
    f"config:{ip}",
    loader=lambda: fetch_config_from_api(ip),
    entity_type="config",
    entity_id=ip,
)
```

### 4.3 阶段三：全量替换（5-7天）

#### 替换文件清单

| 原文件 | 替换方式 | 说明 |
|--------|----------|------|
| `cache.py` | 删除 | 使用 `MemoryCache` |
| `cache_manager.py` | 删除 | 使用 `IntegratedCacheManager` |
| `config_cache_manager.py` | 重构 | 适配新模块 |
| `cache_invalidation.py` | 删除 | 使用 `CacheInvalidationManager` |
| `redis_client.py` | 保留 | 可选使用 `RedisCache` |

#### 迁移脚本

```python
# scripts/migrate_cache.py
"""缓存模块迁移脚本"""

def migrate_cache_keys():
    """迁移现有缓存键"""
    from multilevel_cache import CacheKeyBuilder
    
    # 旧键格式: task_123
    # 新键格式: v1:task:123
    
    mapping = {
        "task_": "v1:bt:",
        "server_": "v1:sn:",
        "config_": "v1:cfg:",
    }
    
    # 执行键迁移
    for old_prefix, new_prefix in mapping.items():
        keys = redis.keys(f"{old_prefix}*")
        for old_key in keys:
            new_key = old_key.replace(old_prefix, new_prefix, 1)
            value = redis.get(old_key)
            redis.set(new_key, value)
            redis.delete(old_key)
```

### 4.4 阶段四：验证与优化（3-5天）

#### 验证清单

- [ ] 功能验证
  - [ ] 缓存读写正常
  - [ ] 失效机制正常
  - [ ] MQ同步正常
  - [ ] 版本控制正常

- [ ] 性能验证
  - [ ] L1命中率 >= 90%
  - [ ] L2命中率 >= 95%
  - [ ] P99延迟 < 5ms

- [ ] 稳定性验证
  - [ ] Redis故障降级正常
  - [ ] MQ故障降级正常
  - [ ] 内存限制生效

---

## 五、兼容性保障措施

### 5.1 接口兼容层

```python
# backend/app/core/cache_compat.py
"""兼容层 - 保持原有接口"""

class SimpleCache:
    """兼容原有SimpleCache接口"""
    
    def __init__(self, max_size=1000, ttl=300):
        from multilevel_cache import MemoryCache, MemoryCacheConfig
        self._cache = MemoryCache(MemoryCacheConfig(
            max_size=max_size,
            default_ttl=ttl,
        ))
    
    def get(self, key):
        return self._cache.get(key)
    
    def set(self, key, value, ttl=None):
        return self._cache.set(key, value, ttl)
    
    def delete(self, key):
        return self._cache.delete(key)
```

### 5.2 配置兼容

```python
# 保持原有配置格式
CACHE_CONFIG = {
    "L1_MAX_SIZE": 1000,
    "L1_TTL": 300,
    "L2_TTL": 1800,
}

# 转换为新模块配置
def convert_config(old_config):
    from multilevel_cache import IntegratedCacheConfig
    return IntegratedCacheConfig(
        l1_max_size=old_config["L1_MAX_SIZE"],
        l1_ttl=old_config["L1_TTL"],
        l2_ttl=old_config["L2_TTL"],
    )
```

### 5.3 数据迁移

```python
# 迁移期间保持双写
def set_with_migration(key, value, ttl):
    # 写入旧缓存
    old_cache.set(key, value, ttl)
    
    # 写入新缓存
    new_cache.set(key, value, ttl)
```

---

## 六、风险控制

### 6.1 风险识别

| 风险类型 | 风险描述 | 影响程度 | 应对措施 |
|----------|----------|----------|----------|
| **数据丢失** | 迁移过程中缓存数据丢失 | 高 | 双写机制 |
| **性能下降** | 新模块性能不如预期 | 中 | 性能测试验证 |
| **兼容性问题** | 接口不兼容导致报错 | 中 | 兼容层适配 |
| **MQ故障** | 消息队列同步失败 | 中 | 降级机制 |
| **内存溢出** | 缓存占用过多内存 | 高 | 资源监控 |

### 6.2 回滚方案

```python
# 回滚开关
ENABLE_NEW_CACHE = os.getenv("ENABLE_NEW_CACHE", "false").lower() == "true"

def get_cache():
    if ENABLE_NEW_CACHE:
        return new_cache_manager
    else:
        return old_cache_manager
```

### 6.3 监控告警

```python
# 关键指标监控
METRICS = {
    "cache_hit_rate": {"warning": 80, "critical": 60},
    "cache_latency_p99": {"warning": 10, "critical": 50},
    "memory_usage_mb": {"warning": 400, "critical": 480},
}
```

---

## 七、时间计划

```
Week 1:
├── Day 1-2: 准备阶段
│   ├── 安装依赖
│   ├── 创建适配器
│   └── 编写测试
│
├── Day 3-5: 灰度替换
│   ├── 新功能使用新模块
│   ├── 非核心功能替换
│   └── 监控指标验证
│
├── Day 6-7: 全量替换
│   ├── 核心功能替换
│   ├── 数据迁移
│   └── 清理旧代码
│
└── Week 2:
    ├── Day 1-3: 验证优化
    │   ├── 功能验证
    │   ├── 性能验证
    │   └── 稳定性验证
    │
    └── Day 4-5: 文档更新
        ├── API文档更新
        ├── 运维文档更新
        └── 培训材料准备
```

---

## 八、验收标准

### 8.1 功能验收

- [ ] 所有缓存操作正常
- [ ] 缓存失效机制正常
- [ ] MQ同步正常工作
- [ ] 版本控制正常工作
- [ ] 降级机制正常触发

### 8.2 性能验收

| 指标 | 目标值 | 验收标准 |
|------|--------|----------|
| L1命中率 | >= 90% | >= 85% |
| L2命中率 | >= 95% | >= 90% |
| P99延迟 | < 5ms | < 10ms |
| 内存使用 | < 512MB | < 600MB |

### 8.3 稳定性验收

- [ ] 连续运行7天无故障
- [ ] Redis故障降级正常
- [ ] MQ故障降级正常
- [ ] 高并发场景稳定

---

## 九、后续优化建议

1. **性能优化**
   - 实现缓存预热机制
   - 优化序列化性能
   - 添加批量操作支持

2. **功能增强**
   - 支持更多MQ类型（Kafka等）
   - 添加分布式追踪
   - 实现缓存分析报告

3. **运维增强**
   - 完善监控大盘
   - 添加自动化运维脚本
   - 实现故障自愈机制
