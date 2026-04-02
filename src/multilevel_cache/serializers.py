"""
序列化模块 - 提供缓存值的序列化和反序列化功能
"""

import json
import logging
import pickle
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)


class CacheSerializer:
    """
    缓存序列化器
    
    支持多种序列化格式：
    - JSON（默认）
    - Pickle（用于复杂对象）
    - 自定义序列化器
    """
    
    def __init__(
        self,
        default_format: str = "json",
        encoding: str = "utf-8",
    ):
        self.default_format = default_format
        self.encoding = encoding
        
        self._custom_encoders = {}
        self._custom_decoders = {}
    
    def register_encoder(self, type_cls, encoder: callable):
        """注册自定义编码器"""
        self._custom_encoders[type_cls] = encoder
    
    def register_decoder(self, type_name: str, decoder: callable):
        """注册自定义解码器"""
        self._custom_decoders[type_name] = decoder
    
    def serialize(self, value: Any, format: str = None) -> Union[str, bytes]:
        """
        序列化值
        
        Args:
            value: 要序列化的值
            format: 序列化格式 (json/pickle)
        
        Returns:
            序列化后的字符串或字节
        """
        fmt = format or self.default_format
        
        if value is None:
            return "null"
        
        if isinstance(value, (str, int, float, bool)):
            return str(value)
        
        if fmt == "pickle":
            return self._pickle_encode(value)
        
        return self._json_encode(value)
    
    def deserialize(self, value: Union[str, bytes, None]) -> Any:
        """
        反序列化值
        
        Args:
            value: 序列化的值
        
        Returns:
            反序列化后的对象
        """
        if value is None:
            return None
        
        if isinstance(value, bytes):
            return self._decode_bytes(value)
        
        if isinstance(value, str):
            if value == "null":
                return None
            
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return value
        
        return value
    
    def _json_encode(self, value: Any) -> str:
        """JSON编码"""
        def default_encoder(obj):
            if isinstance(obj, datetime):
                return {"__type__": "datetime", "value": obj.isoformat()}
            if isinstance(obj, date):
                return {"__type__": "date", "value": obj.isoformat()}
            if isinstance(obj, Decimal):
                return {"__type__": "decimal", "value": str(obj)}
            if isinstance(obj, bytes):
                return {"__type__": "bytes", "value": obj.hex()}
            
            for type_cls, encoder in self._custom_encoders.items():
                if isinstance(obj, type_cls):
                    return encoder(obj)
            
            raise TypeError(f"Object of type {type(obj)} is not JSON serializable")
        
        return json.dumps(value, default=default_encoder, ensure_ascii=False)
    
    def _decode_bytes(self, value: bytes) -> Any:
        """解码字节"""
        try:
            decoded = value.decode(self.encoding)
            return self.deserialize(decoded)
        except UnicodeDecodeError:
            return self._pickle_decode(value)
    
    def _pickle_encode(self, value: Any) -> bytes:
        """Pickle编码"""
        return pickle.dumps(value)
    
    def _pickle_decode(self, value: bytes) -> Any:
        """Pickle解码"""
        try:
            return pickle.loads(value)
        except Exception as e:
            logger.error(f"Pickle解码失败: {str(e)}")
            return None


class JSONSerializer(CacheSerializer):
    """JSON专用序列化器"""
    
    def __init__(self, encoding: str = "utf-8"):
        super().__init__(default_format="json", encoding=encoding)


class PickleSerializer(CacheSerializer):
    """Pickle专用序列化器"""
    
    def __init__(self, encoding: str = "utf-8"):
        super().__init__(default_format="pickle", encoding=encoding)


def serialize(value: Any) -> Union[str, bytes]:
    """便捷序列化函数"""
    return CacheSerializer().serialize(value)


def deserialize(value: Union[str, bytes, None]) -> Any:
    """便捷反序列化函数"""
    return CacheSerializer().deserialize(value)
