# 多级缓存模块 (Multi-Level Cache)

一个可独立安装、复用的多级缓存Python模块，支持L1内存缓存、L2 Redis缓存和L3数据库回源。

## 特性

- **多级缓存架构**: 支持 L1(内存) → L2(Redis) → L3(数据库) 三级缓存
- **防护机制**: 缓存穿透、击穿、雪崩防护
- **自动降级**: Redis故障时自动降级到L1缓存
- **分布式锁**: 基于Redis的分布式锁实现
- **布隆过滤器**: 防止缓存穿透
- **熔断器**: 防止级联故障
- **性能监控**: 实时统计和告警
- **装饰器支持**: 简洁的缓存装饰器
- **线程安全**: 所有操作都是线程安全的

## 环境要求

- Python 3.8+
- Redis 5.0+ (可选，用于L2分布式缓存)

## 安装

### 方式一：从 PyPI 安装（推荐）

```bash
pip install multilevel-cache
```

### 方式二：从 Git 仓库安装

```bash
# 直接从 Git 仓库安装
pip install git+https://github.com/yourusername/multilevel-cache.git

# 或安装特定分支/标签
pip install git+https://github.com/yourusername/multilevel-cache.git@main
pip install git+https://github.com/yourusername/multilevel-cache.git@v1.1.0

# 使用 SSH 方式安装（适用于私有仓库）
pip install git+ssh://git@github.com/yourusername/multilevel-cache.git
```

### 方式三：从源码安装（开发模式）

```bash
# 克隆仓库
git clone https://github.com/yourusername/multilevel-cache.git
cd multilevel-cache

# 安装开发依赖
pip install -e ".[dev]"
```

## 快速开始

### 基本使用

```python
from multilevel_cache import CacheManager, CacheConfig

# 创建缓存管理器
config = CacheConfig(
    name="my_cache",
    memory_config={"max_size": 1000, "default_ttl": 300},
    redis_config={"host": "localhost", "port": 6379},
)
cache = CacheManager(config)

# 设置缓存
cache.set("user:123", {"name": "Alice", "age": 30})

# 获取缓存
user = cache.get("user:123")
print(user)  # {'name': 'Alice', 'age': 30}

# 带回源函数的获取
def load_user():
    return db.query(User).get(123)

user = cache.get("user:123", loader=load_user, ttl=600)
```

### 使用装饰器

```python
from multilevel_cache import cached

@cached(key_prefix="user", ttl=300)
def get_user(user_id: int):
    return db.query(User).get(user_id)

# 第一次调用会执行函数并缓存结果
user = get_user(123)

# 第二次调用直接从缓存返回
user = get_user(123)
```

### 异步支持

```python
from multilevel_cache import cached_async

@cached_async(key_prefix="user", ttl=300)
async def get_user_async(user_id: int):
    return await db.query(User).get(user_id)
```

### 缓存失效

```python
# 删除单个缓存
cache.delete("user:123")

# 按模式删除
cache.delete_pattern("user:*")

# 清空所有缓存
cache.clear()
```

## 配置说明

### 完整配置示例

```python
from multilevel_cache import CacheConfig, CacheStrategy

config = CacheConfig(
    name="my_cache",
    strategy=CacheStrategy.READ_THROUGH,
    
    # 内存缓存配置
    memory_config={
        "max_size": 1000,
        "default_ttl": 300,
        "eviction_policy": "lru",  # lru, lfu, fifo, ttl
        "thread_safe": True,
    },
    
    # Redis配置
    redis_config={
        "host": "localhost",
        "port": 6379,
        "db": 0,
        "password": None,
        "ssl": False,
        "socket_timeout": 5,
        "max_connections": 50,
    },
    
    # TTL配置
    ttl_config={
        "default": 300,
        "l1_ttl": 300,
        "l2_ttl": 1800,
        "null_value_ttl": 60,
        "lock_timeout": 10,
        "jitter_min": 0.9,
        "jitter_max": 1.1,
    },
    
    # 防护配置
    protection_config={
        "enable_penetration_protection": True,
        "enable_breakdown_protection": True,
        "enable_bloom_filter": False,
        "bloom_filter_size": 100000,
        "max_retry_attempts": 3,
    },
    
    # 降级配置
    degradation_config={
        "enable_auto_degradation": True,
        "failure_threshold": 3,
        "recovery_check_interval": 30,
    },
    
    # 监控配置
    enable_metrics=True,
    enable_logging=True,
    log_level="INFO",
)
```

### 从字典创建配置

```python
config_dict = {
    "name": "my_cache",
    "memory": {"max_size": 500},
    "redis": {"host": "localhost", "port": 6379},
    "ttl": {"default": 600},
}

config = CacheConfig.from_dict(config_dict)
```

## 缓存键构建

```python
from multilevel_cache import CacheKeyBuilder

# 构建缓存键
key = CacheKeyBuilder.build("user", 123)
# 结果: "v1:user:123"

# 带额外部分
key = CacheKeyBuilder.build("user", 123, "profile", "avatar")
# 结果: "v1:user:123:profile:avatar"

# 构建匹配模式
pattern = CacheKeyBuilder.build_pattern("user")
# 结果: "v1:user:*"

# 解析缓存键
parts = CacheKeyBuilder.parse("v1:user:123:profile")
# 结果: {"version": "v1", "prefix": "user", "identifier": "123", "extra": ["profile"]}
```

## 缓存防护

### 防止缓存穿透

```python
# 空值会被缓存，避免频繁查询数据库
value = cache.get("user:999", loader=lambda: None)
# 空值会被标记为 "__NULL__" 并缓存60秒
```

### 防止缓存击穿

```python
from multilevel_cache import DistributedLock

# 使用分布式锁
lock = DistributedLock(redis_client, "hot_key", timeout=10)
if lock.acquire():
    try:
        value = load_expensive_data()
        cache.set("hot_key", value)
    finally:
        lock.release()

# 或使用上下文管理器
with DistributedLock(redis_client, "hot_key"):
    value = load_expensive_data()
    cache.set("hot_key", value)
```

### 防止缓存雪崩

```python
# TTL会自动添加随机抖动(默认±10%)
cache.set("key", "value", ttl=100)
# 实际TTL可能在90-110秒之间
```

### 布隆过滤器

```python
from multilevel_cache import BloomFilter

bf = BloomFilter(redis_client, "user_filter", size=100000)

# 添加元素
bf.add("user:123")

# 检查元素是否存在
if bf.exists("user:123"):
    # 可能存在
    pass

if not bf.exists("user:999"):
    # 一定不存在
    pass
```

### 熔断器

```python
from multilevel_cache import CircuitBreaker

cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30)

if cb.is_available():
    try:
        result = cache.get("key")
        cb.record_success()
    except Exception:
        cb.record_failure()
else:
    # 熔断器打开，使用降级逻辑
    result = fallback()
```

## 性能监控

```python
from multilevel_cache import CacheMonitor

monitor = CacheMonitor()

# 记录操作
monitor.record_hit("l1")
monitor.record_miss("l2")
monitor.record_error("connection")

# 获取统计
stats = monitor.get_stats()
print(stats)

# 导出Prometheus格式
prometheus_metrics = monitor.export_prometheus()
print(prometheus_metrics)
```

## API参考

### CacheManager

| 方法 | 说明 |
|------|------|
| `get(key, loader=None, ttl=None)` | 获取缓存值 |
| `set(key, value, ttl=None)` | 设置缓存值 |
| `delete(key)` | 删除缓存 |
| `delete_pattern(pattern)` | 按模式删除 |
| `clear()` | 清空所有缓存 |
| `get_stats()` | 获取统计信息 |
| `enable()` | 启用缓存 |
| `disable()` | 禁用缓存 |
| `is_enabled()` | 检查是否启用 |

### MemoryCache

| 方法 | 说明 |
|------|------|
| `get(key)` | 获取缓存值 |
| `set(key, value, ttl=None)` | 设置缓存值 |
| `delete(key)` | 删除缓存 |
| `exists(key)` | 检查键是否存在 |
| `clear()` | 清空缓存 |
| `get_stats()` | 获取统计信息 |
| `keys()` | 获取所有键 |

### RedisCache

| 方法 | 说明 |
|------|------|
| `get(key)` | 获取缓存值 |
| `set(key, value, ttl=None)` | 设置缓存值 |
| `delete(key)` | 删除缓存 |
| `exists(key)` | 检查键是否存在 |
| `keys(pattern)` | 按模式查找键 |
| `delete_pattern(pattern)` | 按模式删除 |
| `get_many(keys)` | 批量获取 |
| `set_many(mapping, ttl)` | 批量设置 |
| `incr(key, amount)` | 原子递增 |
| `expire(key, seconds)` | 设置过期时间 |
| `ttl(key)` | 获取剩余过期时间 |

## 运行测试

```bash
# 安装开发依赖
pip install -e ".[dev]"

# 运行测试
pytest src/multilevel_cache/tests/ -v

# 运行测试并生成覆盖率报告
pytest src/multilevel_cache/tests/ -v --cov=multilevel_cache --cov-report=html
```

## 常见问题

### Q: 如何在没有 Redis 的情况下使用？

A: 可以只使用 L1 内存缓存，不配置 Redis：

```python
from multilevel_cache import CacheManager, CacheConfig

config = CacheConfig(
    name="my_cache",
    memory_config={"max_size": 1000, "default_ttl": 300},
)
cache = CacheManager(config)
```

### Q: 如何处理 Redis 连接失败？

A: 模块内置自动降级机制，当 Redis 不可用时会自动降级到 L1 缓存：

```python
config = CacheConfig(
    degradation_config={
        "enable_auto_degradation": True,
        "failure_threshold": 3,
        "recovery_check_interval": 30,
    }
)
```

### Q: 如何自定义缓存键格式？

A: 使用 `CacheKeyBuilder` 或自定义 `key_builder` 函数：

```python
def custom_key_builder(user_id):
    return f"custom:user:{user_id}:v2"

@cached(key_builder=custom_key_builder, ttl=300)
def get_user(user_id):
    return db.query(User).get(user_id)
```

### Q: 安装时出现依赖冲突怎么办？

A: 尝试使用虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows
pip install multilevel-cache
```

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件