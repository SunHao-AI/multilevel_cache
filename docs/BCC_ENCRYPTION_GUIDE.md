# PyArmor BCC加密完整使用指南

> **文档版本**: v1.0  
> **创建日期**: 2025-04-03  
> **适用项目**: multilevel_cache v1.1.1  
> **PyArmor版本**: 9.0+ (专家版)

---

## 目录

1. [BCC加密基本概念和优势](#1-bcc加密基本概念和优势)
2. [安装配置步骤](#2-安装配置步骤)
3. [加密命令参数设置](#3-加密命令参数设置)
4. [加密过程执行流程和验证](#4-加密过程执行流程和验证)
5. [项目文件选择策略](#5-项目文件选择策略)
6. [兼容性问题及解决方案](#6-兼容性问题及解决方案)
7. [最佳实践建议](#7-最佳实践建议)
8. [快速开始指南](#8-快速开始指南)

---

## 1. BCC加密基本概念和优势

### 1.1 什么是BCC模式？

**BCC模式** 是PyArmor专家版提供的最强加密模式,它能够将Python函数和方法转换为等效的C函数,然后编译成机器指令直接执行。这种加密方式从根本上避免了被还原成Python源代码。

### 1.2 BCC模式的核心优势

| 优势 | 说明 | 安全级别 |
|------|------|---------|
| **不可逆性** | 函数被转换为二进制机器码,无法反编译回Python代码 | ⭐⭐⭐⭐⭐ |
| **高性能** | 编译后的C代码执行效率更高 | ⭐⭐⭐⭐ |
| **深层保护** | 即使运行时内存被dump,也无法获取原始Python代码逻辑 | ⭐⭐⭐⭐⭐ |
| **兼容性** | 加密后的脚本仍可作为正常Python脚本使用 | ⭐⭐⭐⭐ |

### 1.3 BCC模式工作原理

```
Python源代码 → AST分析 → C代码生成 → clang编译 → 机器指令 → 加密脚本执行
```

**关键特性**:
- 模块级别的代码不会被转换(仍使用普通加密)
- 使用不支持的Python特性的函数不会被转换
- 未转换的函数会使用其他加密方式保护

---

## 2. 安装配置步骤

### 2.1 PyArmor安装和注册

#### 步骤1: 安装PyArmor

```bash
pip install -U pyarmor
pyarmor -v  # 检查版本,确保是9.0+
```

#### 步骤2: 注册专家版许可证

您已经拥有PyArmor专家版许可证文件,有两种注册方式:

**方式一: 使用激活码注册(首次注册)**

```bash
pyarmor reg -p multilevel-cache D:\WorkPlace\Pycharm\pyarmor\pyarmor-regcode-11267.txt
```

**方式二: 使用注册文件注册(推荐)**

```bash
pyarmor reg D:\WorkPlace\Pycharm\pyarmor\pyarmor-regfile-11267.zip
pyarmor -v  # 验证注册信息
```

**重要提示**:
- 注册文件`pyarmor-regfile-11267.zip`最多可在100台设备上使用
- 每台设备只需注册一次,不要在每次加密前重复注册
- 不要在Docker容器或CI/CD流程中使用注册文件(每次运行会被计为新设备)

### 2.2 配置clang编译器(Windows环境)

BCC模式在Windows下**仅支持clang.exe**,需要按以下方式之一配置:

#### 方式一: 使用已有的clang.exe

```bash
clang --version  # 检查clang是否可用

# 如果clang存在但无法在任意路径运行,设置环境变量
set PYARMOR_CC=C:\path\to\clang.exe
```

#### 方式二: 安装LLVM官方版本

从 https://releases.llvm.org 下载并安装Windows预编译版本

#### 方式三: 使用PyArmor提供的精简版(推荐)

```bash
# 下载地址: https://pyarmor.dashingsoft.com/downloads/tools/clang-9.0.zip
# 解压后将clang.exe保存到用户根目录的.pyarmor文件夹
# Windows下默认路径: %HOME%\.pyarmor\ 或 %USERPROFILE%\.pyarmor\
```

---

## 3. 加密命令参数设置

### 3.1 基础BCC加密命令

```bash
pyarmor gen --enable-bcc src/multilevel_cache
pyarmor gen --enable-bcc -O dist src/multilevel_cache
```

### 3.2 高级安全配置(推荐用于生产环境)

```bash
pyarmor gen --enable-bcc --enable-jit --mix-str --assert-call --assert-import --restrict -O dist src/multilevel_cache
```

### 3.3 参数详解表

| 参数 | 功能说明 | 适用场景 | 安全级别 |
|------|---------|---------|---------|
| `--enable-bcc` | 启用BCC模式,将函数转换为C代码编译成机器码 | 核心算法保护 | ⭐⭐⭐⭐⭐ |
| `--enable-jit` | 使用动态指令生成技术处理敏感数据 | 增强安全性 | ⭐⭐⭐⭐ |
| `--mix-str` | 加密所有长度>8的字符串常量 | 防止字符串泄露 | ⭐⭐⭐⭐ |
| `--assert-call` | 确保加密函数不被替换 | 防止函数篡改 | ⭐⭐⭐⭐ |
| `--assert-import` | 确保导入的模块是加密模块 | 防止模块替换 | ⭐⭐⭐⭐ |
| `--restrict` | 确保加密模块只能在内部使用 | 防止外部导入 | ⭐⭐⭐⭐⭐ |
| `-O dist` | 指定输出目录 | 组织输出文件 | - |
| `-r` | 递归处理子目录 | 包含所有子包 | - |

### 3.4 针对包的特殊配置

#### 配置1: 允许外部导入特定模块

```bash
pyarmor cfg exclude_restrict_modules="multilevel_cache.__init__"
pyarmor gen --enable-bcc --restrict -O dist src/multilevel_cache
```

#### 配置2: 使用只读模式(替代restrict)

```bash
pyarmor cfg readonly_module=1
pyarmor gen --enable-bcc --mix-str --assert-call -O dist src/multilevel_cache
```

### 3.5 其他重要参数

```bash
pyarmor gen --enable-bcc -e 2025-12-31 -O dist src/multilevel_cache
pyarmor gen --enable-bcc -b "66:77:88:9a:cc:fa" -O dist src/multilevel_cache
pyarmor gen --enable-bcc --period 1 -O dist src/multilevel_cache
pyarmor gen --enable-bcc --outer -O dist src/multilevel_cache
pyarmor gen key -e 3
```

---

## 4. 加密过程执行流程和验证

### 4.1 完整加密执行流程

#### 步骤1: 启用跟踪日志

```bash
pyarmor cfg enable_trace=1
```

#### 步骤2: 执行加密命令

```bash
cd d:\WorkPlace\Pycharm\multilevel_cache
pyarmor gen --enable-bcc --enable-jit --mix-str --assert-call --assert-import --restrict -r -O dist src/multilevel_cache
```

#### 步骤3: 查看加密日志

```bash
cat pyarmor.trace.log
grep trace.bcc pyarmor.trace.log
```

**日志示例**:
```
trace.bcc            core:15:CacheBackend.get
trace.bcc            core:28:MemoryCache.set
trace.bcc            decorators:10:cached
trace.bcc !          protection:45:DistributedLock.acquire (unsupported function "super")
```

#### 步骤4: 检查输出目录结构

```bash
ls dist/
ls dist/multilevel_cache/
ls dist/pyarmor_runtime_000000/
```

**预期输出结构**:
```
dist/
├── multilevel_cache/
│   ├── __init__.py          (加密后)
│   ├── core.py              (加密后)
│   ├── decorators.py        (加密后)
│   ├── ...其他模块.py
│   └── tests/               (如果包含)
└── pyarmor_runtime_000000/  (运行辅助包)
    ├── __init__.py
    ├── pyarmor_runtime.so/dll
    └── ...
```

### 4.2 加密效果验证方法

#### 方法1: 功能测试验证

```bash
cd dist
python -c "import multilevel_cache; print('导入成功'); print(multilevel_cache.__version__)"
python -m pytest multilevel_cache/tests/ -v
```

#### 方法2: 源码查看验证

```bash
cat dist/multilevel_cache/core.py
```

加密后的文件应该包含类似内容:
```python
from pyarmor_runtime_000000 import __pyarmor__
__pyarmor__(__name__, __file__, b'\x50\x59\x41...')
```

#### 方法3: 反编译测试

```bash
pip install uncompyle6
uncompyle6 dist/multilevel_cache/core.py
```

预期结果: 无法反编译或显示加密保护信息

#### 方法4: 运行时保护验证

创建测试脚本 `test_protection.py`:
```python
import sys
sys.path.insert(0, 'dist')

import multilevel_cache

try:
    print(multilevel_cache.CacheBackend.__code__)
except Exception as e:
    print(f"保护生效: {e}")

try:
    multilevel_cache.new_attr = "test"
    print("警告: 模块属性可被修改")
except RuntimeError as e:
    print(f"只读保护生效: {e}")
```

### 4.3 BCC转换效果验证

```bash
grep "trace.bcc" pyarmor.trace.log | grep -v "!"

total_functions=$(grep "trace.co" pyarmor.trace.log | wc -l)
bcc_functions=$(grep "trace.bcc" pyarmor.trace.log | grep -v "!" | wc -l)
echo "BCC转换率: $bcc_functions / $total_functions"
```

---

## 5. 项目文件选择策略

### 5.1 需要加密的文件范围

#### 必须加密的核心文件

```
src/multilevel_cache/
├── __init__.py          ✓ 必须加密(包入口,导出接口)
├── core.py              ✓ 必须加密(核心缓存逻辑)
├── decorators.py        ✓ 必须加密(装饰器实现)
├── protection.py        ✓ 必须加密(防护机制)
├── monitoring.py        ✓ 必须加密(监控统计)
├── sync.py              ✓ 必须加密(MQ同步)
├── version.py           ✓ 必须加密(版本控制)
├── invalidation.py      ✓ 必须加密(失效规则)
├── resource.py          ✓ 必须加密(资源监控)
├── integrated.py        ✓ 必须加密(集成管理器)
├── config.py            ✓ 必须加密(配置系统)
├── exceptions.py        ✓ 必须加密(异常定义)
├── serializers.py       ✓ 必须加密(序列化)
└── integrations.py      ✓ 必须加密(集成功能)
```

#### 可选加密的测试文件

```
src/multilevel_cache/tests/
├── __init__.py          ○ 可不加密(测试辅助)
├── test_*.py            ○ 可不加密(测试代码,通常不发布)
```

### 5.2 加密范围规划方案

#### 方案1: 全包加密(推荐用于商业发布)

```bash
pyarmor gen --enable-bcc --enable-jit --mix-str --assert-call --assert-import --restrict -r -O dist src/multilevel_cache
pyarmor gen --enable-bcc --enable-jit --mix-str --assert-call --assert-import --restrict --exclude "tests" -O dist src/multilevel_cache
```

#### 方案2: 核心模块加密(用于开源项目)

```bash
pyarmor gen --enable-bcc --enable-jit --mix-str --assert-call -O dist \
    src/multilevel_cache/core.py \
    src/multilevel_cache/decorators.py \
    src/multilevel_cache/protection.py \
    src/multilevel_cache/monitoring.py \
    src/multilevel_cache/sync.py \
    src/multilevel_cache/version.py \
    src/multilevel_cache/invalidation.py \
    src/multilevel_cache/resource.py \
    src/multilevel_cache/integrated.py
```

#### 方案3: 分层加密(灵活控制)

创建加密清单文件 `encrypt_list.txt`:
```
src/multilevel_cache/core.py
src/multilevel_cache/decorators.py
src/multilevel_cache/protection.py
src/multilevel_cache/monitoring.py
src/multilevel_cache/sync.py
src/multilevel_cache/version.py
src/multilevel_cache/invalidation.py
src/multilevel_cache/resource.py
src/multilevel_cache/integrated.py
src/multilevel_cache/config.py
src/multilevel_cache/serializers.py
src/multilevel_cache/integrations.py
```

使用清单文件加密:
```bash
pyarmor gen --enable-bcc --enable-jit --mix-str --assert-call -O dist @encrypt_list.txt
```

### 5.3 数据文件处理策略

```bash
pyarmor cfg data_files="*.json *.yaml *.cfg *.txt"
pyarmor gen --enable-bcc -O dist src/multilevel_cache

mkdir -p dist/multilevel_cache
cp -a src/multilevel_cache/*.json dist/multilevel_cache/
cp -a src/multilevel_cache/*.yaml dist/multilevel_cache/
pyarmor gen --enable-bcc -O dist -r src/multilevel_cache
```

---

## 6. 兼容性问题及解决方案

### 6.1 BCC模式不支持的Python特性

#### 问题1: 使用super()的类方法

**问题代码**:
```python
class ChildClass(ParentClass):
    def method(self):
        super().method()  # BCC不支持
```

**解决方案**:
```bash
pyarmor cfg -p multilevel_cache.core bcc:excludes="ChildClass.method"
pyarmor cfg -p multilevel_cache.core bcc:excludes="ChildClass.*"
```

#### 问题2: 使用装饰器的函数

**解决方案**:
```bash
pyarmor cfg -p multilevel_cache.decorators bcc:excludes="cached cached_async"
```

#### 问题3: 使用yield的生成器函数

**解决方案**:
```bash
pyarmor cfg -p multilevel_cache.core bcc:excludes="generator_function"
```

#### 问题4: 嵌套函数和嵌套类

**问题代码**:
```python
def outer():
    def inner():  # BCC无法处理嵌套函数
        pass
    class InnerClass:  # BCC无法处理嵌套类
        pass
```

**解决方案**:
```bash
pyarmor cfg -p multilevel_cache.core bcc:excludes="outer"
```

### 6.2 运行时兼容性问题

#### 问题5: 外部脚本导入加密模块失败

**错误示例**:
```python
from multilevel_cache import RedisCache
# RuntimeError: unauthorized use of script
```

**解决方案**:
```bash
pyarmor gen --enable-bcc --mix-str --assert-call -O dist src/multilevel_cache

pyarmor cfg exclude_restrict_modules="multilevel_cache.__init__ multilevel_cache.core"
pyarmor gen --enable-bcc --restrict -O dist src/multilevel_cache

pyarmor cfg readonly_module=1
pyarmor gen --enable-bcc --mix-str -O dist src/multilevel_cache
```

#### 问题6: 动态属性访问失败

**解决方案**:
```bash
pyarmor gen --enable-bcc --mix-str -O dist src/multilevel_cache
```

### 6.3 编译器相关问题

#### 问题7: Windows下clang编译失败

**解决方案**:
```bash
pyarmor cfg windows.x86_64.bcc:cflags += " -DENABLE_BCC_MEMSET"

clang --version
set PYARMOR_CC=C:\correct\path\to\clang.exe
```

#### 问题8: 32位系统编译问题

**解决方案**:
```bash
pyarmor cfg windows.x86.bcc:cflags += " -DENABLE_BCC_MEMSET"
```

### 6.4 性能和内存问题

#### 问题9: 加密后运行速度变慢

**解决方案**:
```bash
grep trace.bcc pyarmor.trace.log | grep -v "!" | wc -l
pyarmor cfg -p problematic_module bcc:disabled=1
```

#### 问题10: 内存占用增加

**解决方案**:
```bash
pyarmor gen runtime -O build/shared_runtime
pyarmor gen --enable-bcc --use-runtime build/shared_runtime -O dist src/multilevel_cache
cp -a build/shared_runtime/pyarmor_runtime_000000 dist/
```

### 6.5 调试和排查流程

```bash
pyarmor -d gen --enable-bcc src/multilevel_cache
cat pyarmor.debug.log

pyarmor cfg enable_trace=1
pyarmor gen --enable-bcc src/multilevel_cache
cat pyarmor.trace.log

grep "trace.bcc !" pyarmor.trace.log

pyarmor cfg -p module_name bcc:excludes="problem_function"

pyarmor gen --enable-bcc -O dist src/multilevel_cache
python -c "import sys; sys.path.insert(0, 'dist'); import multilevel_cache"
```

---

## 7. 最佳实践建议

### 7.1 加密前准备工作

#### 最佳实践1: 代码质量检查

```bash
python -m py_compile src/multilevel_cache/*.py
python -m mypy src/multilevel_cache/ --ignore-missing-imports
python -m pytest src/multilevel_cache/tests/ -v
```

#### 最佳实践2: 代码结构优化

**不推荐**:
```python
class Child(Parent):
    def method(self):
        super().method()  # BCC不支持
```

**推荐**:
```python
class Child(Parent):
    def method(self):
        Parent.method(self)  # BCC支持
```

#### 最佳实践3: 备份原始代码

```bash
git add .
git commit -m "Pre-encryption backup"
git tag v1.1.1-pre-encrypt

tar -czf multilevel_cache_backup.tar.gz src/
```

### 7.2 加密配置最佳实践

#### 最佳实践4: 分阶段加密

```bash
pyarmor gen --enable-bcc -O dist_test src/multilevel_cache
python -m pytest dist_test/multilevel_cache/tests/ -v

pyarmor gen --enable-bcc --enable-jit --mix-str -O dist_enhanced src/multilevel_cache
python -m pytest dist_enhanced/multilevel_cache/tests/ -v

pyarmor gen --enable-bcc --enable-jit --mix-str --assert-call --assert-import --restrict -O dist_production src/multilevel_cache
```

#### 最佳实践5: 配置文件管理

创建加密配置文件 `.pyarmor/config.cfg`:
```ini
[bcc]
excludes = "super_method generator_func nested_function"
disabled_modules = "tests"

[mix.str]
threshold = 8
excludes = "/.{1000,}/"

[restrict]
exclude_modules = "__init__"
```

使用配置文件加密:
```bash
pyarmor gen --enable-bcc --restrict -O dist src/multilevel_cache
```

#### 最佳实践6: 模块化配置

```bash
pyarmor cfg -p multilevel_cache.core bcc:includes="*"
pyarmor cfg -p multilevel_cache.core mix.str:threshold=5

pyarmor cfg -p multilevel_cache.config bcc:excludes="validate_config"

pyarmor cfg -p multilevel_cache.exceptions bcc:disabled=1
```

### 7.3 加密后验证最佳实践

#### 最佳实践7: 全面功能测试

创建完整测试脚本 `test_encrypted.py`:
```python
import sys
sys.path.insert(0, 'dist')

import multilevel_cache
print(f"✓ 导入成功,版本: {multilevel_cache.__version__}")

from multilevel_cache import MemoryCache, RedisCache
cache = MemoryCache()
cache.set('test_key', 'test_value', ttl=60)
assert cache.get('test_key') == 'test_value'
print("✓ 核心功能正常")

from multilevel_cache import cached
@cached(ttl=30)
def test_func():
    return "decorated"
assert test_func() == "decorated"
print("✓ 装饰器功能正常")

try:
    from multilevel_cache import CacheException
    raise CacheException("test")
except Exception as e:
    print(f"✓ 异常处理正常: {e}")

print("所有测试通过!")
```

运行测试:
```bash
python test_encrypted.py
```

#### 最佳实践8: 性能基准测试

```bash
python -m timeit -n 1000 -s "from src.multilevel_cache import MemoryCache; c=MemoryCache()" "c.set('k','v',60); c.get('k')"
python -m timeit -n 1000 -s "import sys; sys.path.insert(0,'dist'); from multilevel_cache import MemoryCache; c=MemoryCache()" "c.set('k','v',60); c.get('k')"
```

#### 最佳实践9: 安全性验证

```bash
pip install uncompyle6 decompyle3
uncompyle6 dist/multilevel_cache/core.py 2>&1 | grep -i "error"

head -20 dist/multilevel_cache/core.py

python -c "import sys; sys.path.insert(0,'dist'); import multilevel_cache; multilevel_cache.hacked=1" 2>&1 | grep -i "error"
```

### 7.4 发布和部署最佳实践

#### 最佳实践10: 打包发布

```bash
pip install pyinstaller
pyarmor gen --enable-bcc --pack onefile -O dist_package src/multilevel_cache

cd dist
python -m build --wheel
```

#### 最佳实践11: 版本管理

```bash
git tag v1.1.1-encrypted
git commit -m "Encrypted version with BCC mode"
```

创建加密日志 `ENCRYPTION_LOG.md`:
```markdown
# 加密日志

## 版本: v1.1.1-encrypted
## 加密时间: 2025-04-03
## 加密参数:
- BCC模式: 启用
- JIT模式: 启用
- 字符串混淆: 启用
- 函数保护: 启用
- 模块保护: 启用
- 约束模式: 启用

## BCC转换率: 85%
## 测试结果: 全部通过
```

#### 最佳实践12: 授权管理

```bash
pyarmor gen --enable-bcc -e 2026-04-03 -O dist_client_a src/multilevel_cache

pyarmor gen --enable-bcc -b "00:11:22:33:44:55" -O dist_client_b src/multilevel_cache

pyarmor gen --enable-bcc --outer -O dist_client_c src/multilevel_cache
pyarmor gen key -e 30 -O dist_client_c/key
```

### 7.5 维护和更新最佳实践

#### 最佳实践13: 定期重新加密

```bash
git pull
python -m pytest src/multilevel_cache/tests/
pyarmor gen --enable-bcc --enable-jit --mix-str -O dist src/multilevel_cache
python -m pytest dist/multilevel_cache/tests/
```

#### 最佳实践14: 监控加密效果

```bash
pyarmor cfg enable_trace=1
pyarmor gen --enable-bcc src/multilevel_cache
bcc_rate=$(grep "trace.bcc" pyarmor.trace.log | grep -v "!" | wc -l)
total_rate=$(grep "trace.co" pyarmor.trace.log | wc -l)
echo "BCC转换率: $(echo "scale=2; $bcc_rate/$total_rate*100" | bc)%"
```

### 7.6 安全性增强建议

#### 最佳实践15: 多层保护组合

```bash
pyarmor gen \
    --enable-bcc \
    --enable-jit \
    --enable-rft \
    --mix-str \
    --assert-call \
    --assert-import \
    --restrict \
    --private \
    --period 1 \
    --outer \
    -e 2026-12-31 \
    -O dist_maximum_security \
    src/multilevel_cache
```

#### 最佳实践16: 定期更新密钥

```bash
pyarmor gen key -e 90 -O dist/new_key_$(date +%Y%m%d)
cp dist/new_key_*/pyarmor.rkey dist/pyarmor_runtime_000000/
```

---

## 8. 快速开始指南

### 8.1 5分钟快速上手

```bash
pip install -U pyarmor
pyarmor reg D:\WorkPlace\Pycharm\pyarmor\pyarmor-regfile-11267.zip
pyarmor -v

set PYARMOR_CC=C:\path\to\clang.exe

cd d:\WorkPlace\Pycharm\multilevel_cache

pyarmor cfg enable_trace=1

pyarmor gen --enable-bcc --enable-jit --mix-str --assert-call --assert-import --restrict -r -O dist src/multilevel_cache

python -c "import sys; sys.path.insert(0, 'dist'); import multilevel_cache; print('✓ 加密成功'); print(f'版本: {multilevel_cache.__version__}')"

grep trace.bcc pyarmor.trace.log
```

### 8.2 加密效果预期

根据您的项目结构,预期加密效果:

- **BCC转换率**: 约70-85%的函数会被转换为C代码
- **字符串保护**: 所有长度>8的字符串常量会被加密
- **模块保护**: 外部无法直接导入内部模块
- **函数保护**: 核心函数无法被替换或篡改

### 8.3 重要注意事项

1. **首次使用**: 必须先注册PyArmor专家版许可证
2. **Windows环境**: 必须配置clang.exe编译器
3. **测试验证**: 加密后务必运行完整测试确保功能正常
4. **备份代码**: 加密前备份原始代码,加密后无法还原
5. **授权管理**: 注册文件最多可在100台设备使用

### 8.4 技术支持

- **PyArmor官方文档**: https://pyarmor.readthedocs.io
- **问题排查**: 使用`pyarmor -d gen`生成调试日志
- **项目维护者**: SunHao (2865467769@qq.com)

---

## 附录

### A. 常用命令速查表

| 命令 | 说明 |
|------|------|
| `pyarmor -v` | 查看版本和注册信息 |
| `pyarmor reg <file>` | 注册许可证 |
| `pyarmor gen --enable-bcc <path>` | BCC加密 |
| `pyarmor cfg enable_trace=1` | 启用跟踪日志 |
| `pyarmor cfg -p <module> bcc:excludes="<func>"` | 排除函数 |
| `pyarmor -d gen <path>` | 调试模式加密 |
| `pyarmor gen key -e <days>` | 生成外部密钥 |

### B. 文件路径说明

| 路径 | 说明 |
|------|------|
| `D:\WorkPlace\Pycharm\pyarmor\pyarmor-regfile-11267.zip` | 注册文件 |
| `d:\WorkPlace\Pycharm\multilevel_cache\src\multilevel_cache` | 项目源码 |
| `d:\WorkPlace\Pycharm\multilevel_cache\dist` | 加密输出目录 |
| `%HOME%\.pyarmor\clang.exe` | clang编译器位置 |
| `pyarmor.trace.log` | 跟踪日志文件 |
| `pyarmor.debug.log` | 调试日志文件 |

### C. 错误代码参考

| 错误代码 | 说明 | 解决方案 |
|---------|------|---------|
| error_1 | 脚本许可证已经过期 | 更新许可证或重新生成 |
| error_2 | 脚本许可证不可用于当前设备 | 检查设备绑定配置 |
| error_3 | 缺少运行许可文件 | 检查pyarmor_runtime目录 |
| error_4 | 非法使用脚本 | 检查restrict配置 |
| error_5 | 脚本不支持当前Python版本 | 检查Python版本兼容性 |
| error_6 | 脚本不支持当前系统 | 检查平台配置 |

---

**文档结束**

> 本文档提供了完整的PyArmor BCC加密使用指南,涵盖了从安装配置到实际应用的各个方面。建议按照文档顺序逐步操作,遇到问题时参考第6节的兼容性问题解决方案。