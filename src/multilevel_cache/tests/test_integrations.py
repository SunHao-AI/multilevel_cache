"""
第三方缓存库集成测试
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from multilevel_cache.integrations import (
    CacheAdapter,
    CacheoutAdapter,
    DogpileCacheAdapter,
    ThirdPartyCacheManager,
    create_adapter,
)


class TestCacheoutAdapter:
    """cacheout适配器测试"""
    
    def test_basic_operations(self):
        """测试基本操作"""
        mock_cache = Mock()
        mock_cache.get.return_value = "value1"
        mock_cache.set.return_value = None
        mock_cache.delete.return_value = None
        mock_cache.keys.return_value = ["key1"]
        
        adapter = CacheoutAdapter(cache=mock_cache)
        
        assert adapter.get("key1") == "value1"
        assert adapter.set("key1", "value1") is True
        assert adapter.delete("key1") is True
        
        adapter.clear()
        mock_cache.clear.assert_called_once()
    
    def test_stats(self):
        """测试统计信息"""
        mock_cache = Mock()
        mock_cache.__len__ = Mock(return_value=10)
        
        adapter = CacheoutAdapter(cache=mock_cache, maxsize=100, ttl=300)
        
        stats = adapter.get_stats()
        
        assert stats["maxsize"] == 100
        assert stats["ttl"] == 300


class TestDogpileCacheAdapter:
    """dogpile.cache适配器测试"""
    
    def test_basic_operations(self):
        """测试基本操作"""
        mock_region = Mock()
        mock_region.get.return_value = "value1"
        mock_region.set.return_value = None
        mock_region.delete.return_value = None
        
        adapter = DogpileCacheAdapter(region=mock_region)
        
        assert adapter.get("key1") == "value1"
        assert adapter.set("key1", "value1") is True
        assert adapter.delete("key1") is True
    
    def test_get_or_create(self):
        """测试get_or_create"""
        mock_region = Mock()
        mock_region.get_or_create.return_value = "created_value"
        
        adapter = DogpileCacheAdapter(region=mock_region)
        
        result = adapter.get_or_create("key1", lambda: "new_value")
        
        assert result == "created_value"
        mock_region.get_or_create.assert_called_once()


class TestThirdPartyCacheManager:
    """第三方缓存管理器测试"""
    
    def test_register_and_get(self):
        """测试注册和获取适配器"""
        manager = ThirdPartyCacheManager()
        
        mock_adapter = Mock(spec=CacheAdapter)
        mock_adapter.get.return_value = "value1"
        
        manager.register("test_cache", mock_adapter)
        
        assert manager.get_adapter("test_cache") is mock_adapter
        assert manager.get("test_cache", "key1") == "value1"
    
    def test_set_and_delete(self):
        """测试设置和删除"""
        manager = ThirdPartyCacheManager()
        
        mock_adapter = Mock(spec=CacheAdapter)
        mock_adapter.set.return_value = True
        mock_adapter.delete.return_value = True
        
        manager.register("test_cache", mock_adapter)
        
        assert manager.set("test_cache", "key1", "value1") is True
        assert manager.delete("test_cache", "key1") is True
    
    def test_get_all_stats(self):
        """测试获取所有统计"""
        manager = ThirdPartyCacheManager()
        
        mock_adapter1 = Mock(spec=CacheAdapter)
        mock_adapter1.get_stats.return_value = {"size": 10}
        
        mock_adapter2 = Mock(spec=CacheAdapter)
        mock_adapter2.get_stats.return_value = {"size": 20}
        
        manager.register("cache1", mock_adapter1)
        manager.register("cache2", mock_adapter2)
        
        stats = manager.get_all_stats()
        
        assert "cache1" in stats
        assert "cache2" in stats
        assert stats["cache1"]["size"] == 10
        assert stats["cache2"]["size"] == 20


class TestCreateAdapter:
    """创建适配器工厂测试"""
    
    def test_create_cacheout_adapter(self):
        """测试创建cacheout适配器"""
        with patch("multilevel_cache.integrations.CacheoutAdapter") as mock_cls:
            mock_cls.return_value = Mock()
            
            adapter = create_adapter("cacheout", maxsize=1000)
            
            mock_cls.assert_called_once_with(maxsize=1000)
    
    def test_create_unsupported_adapter(self):
        """测试创建不支持的适配器"""
        with pytest.raises(ValueError) as exc_info:
            create_adapter("unsupported")
        
        assert "不支持的缓存库" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
