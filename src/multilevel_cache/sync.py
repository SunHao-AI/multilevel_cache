"""
消息队列同步模块 - 实现跨服务器缓存同步

支持RabbitMQ作为消息中间件，实现配置更新时的缓存失效通知。
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class MessageType(Enum):
    """消息类型"""
    CONFIG_UPDATE = "config.update"
    CONFIG_DELETE = "config.delete"
    CACHE_INVALIDATE = "cache.invalidate"
    CACHE_CLEAR = "cache.clear"
    HEARTBEAT = "heartbeat"


class UpdateType(Enum):
    """更新类型"""
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


@dataclass
class CacheSyncMessage:
    """缓存同步消息"""
    message_id: str
    message_type: str
    timestamp: str
    cache_keys: List[str] = field(default_factory=list)
    patterns: List[str] = field(default_factory=list)
    config_id: Optional[int] = None
    config_type: Optional[str] = None
    version: int = 0
    update_type: str = "update"
    source: str = "unknown"
    priority: int = 5
    
    def to_json(self) -> str:
        return json.dumps(asdict(self))
    
    @classmethod
    def from_json(cls, json_str: str) -> "CacheSyncMessage":
        data = json.loads(json_str)
        return cls(**data)


@dataclass
class MQConfig:
    """消息队列配置"""
    host: str = "localhost"
    port: int = 5672
    user: str = "guest"
    password: str = "guest"
    virtual_host: str = "/"
    exchange: str = "cache_sync"
    exchange_type: str = "topic"
    routing_key: str = "cache.invalidation"
    queue_name: str = "cache_sync_queue"
    
    connection_timeout: int = 5
    heartbeat: int = 60
    
    retry_attempts: int = 3
    retry_delay: float = 1.0
    
    def to_pika_params(self) -> Dict[str, Any]:
        """转换为pika连接参数"""
        return {
            "host": self.host,
            "port": self.port,
            "credentials": None,
            "virtual_host": self.virtual_host,
            "connection_attempts": self.retry_attempts,
            "retry_delay": self.retry_delay,
            "heartbeat": self.heartbeat,
        }


class MQPublisher:
    """
    RabbitMQ消息发布器
    
    用于发布缓存失效消息到消息队列
    """
    
    def __init__(self, config: MQConfig = None):
        self.config = config or MQConfig()
        self._connection = None
        self._channel = None
        self._available = False
        self._failure_count = 0
        self._lock = threading.Lock()
        
        self._init_connection()
    
    def _init_connection(self) -> None:
        """初始化连接"""
        try:
            import pika
            
            credentials = pika.PlainCredentials(
                self.config.user,
                self.config.password
            )
            
            self._connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self.config.host,
                    port=self.config.port,
                    credentials=credentials,
                    virtual_host=self.config.virtual_host,
                    connection_attempts=self.config.retry_attempts,
                    retry_delay=self.config.retry_delay,
                    heartbeat=self.config.heartbeat,
                )
            )
            
            self._channel = self._connection.channel()
            
            self._channel.exchange_declare(
                exchange=self.config.exchange,
                exchange_type=self.config.exchange_type,
                durable=True
            )
            
            self._available = True
            self._failure_count = 0
            logger.info(f"MQ连接初始化成功: {self.config.host}:{self.config.port}")
            
        except ImportError:
            logger.warning("pika库未安装，MQ同步不可用。请运行: pip install pika")
            self._available = False
        except Exception as e:
            logger.error(f"MQ连接初始化失败: {str(e)}")
            self._available = False
    
    @property
    def is_available(self) -> bool:
        """检查MQ是否可用"""
        return self._available
    
    def publish(
        self,
        message: CacheSyncMessage,
        routing_key: str = None
    ) -> bool:
        """
        发布消息
        
        Args:
            message: 缓存同步消息
            routing_key: 路由键，默认使用配置的路由键
        
        Returns:
            是否发布成功
        """
        if not self._available:
            self._check_recovery()
            if not self._available:
                return False
        
        with self._lock:
            try:
                self._channel.basic_publish(
                    exchange=self.config.exchange,
                    routing_key=routing_key or self.config.routing_key,
                    body=message.to_json(),
                    properties=pika.BasicProperties(
                        delivery_mode=2,
                        content_type="application/json",
                        message_id=message.message_id,
                        timestamp=int(time.time()),
                        priority=message.priority,
                    )
                )
                
                self._failure_count = 0
                logger.debug(f"消息发布成功: {message.message_id}")
                return True
                
            except Exception as e:
                self._handle_failure(e)
                return False
    
    def publish_invalidation(
        self,
        cache_keys: List[str] = None,
        patterns: List[str] = None,
        config_id: int = None,
        config_type: str = None,
        version: int = 0,
        update_type: str = "update",
        source: str = "unknown",
    ) -> bool:
        """
        发布缓存失效消息
        
        Args:
            cache_keys: 要失效的缓存键列表
            patterns: 要失效的缓存模式列表
            config_id: 配置ID
            config_type: 配置类型
            version: 版本号
            update_type: 更新类型
            source: 消息来源
        
        Returns:
            是否发布成功
        """
        import uuid
        
        message = CacheSyncMessage(
            message_id=str(uuid.uuid4()),
            message_type=MessageType.CACHE_INVALIDATE.value,
            timestamp=datetime.now().isoformat(),
            cache_keys=cache_keys or [],
            patterns=patterns or [],
            config_id=config_id,
            config_type=config_type,
            version=version,
            update_type=update_type,
            source=source,
        )
        
        return self.publish(message)
    
    def _check_recovery(self) -> None:
        """检查是否可以恢复连接"""
        if self._failure_count >= 3:
            logger.info("尝试重新连接MQ...")
            self._init_connection()
    
    def _handle_failure(self, error: Exception) -> None:
        """处理失败"""
        self._failure_count += 1
        logger.error(f"MQ发布失败: {str(error)}")
        
        if self._failure_count >= 3:
            self._available = False
            logger.warning("MQ连续失败3次，标记为不可用")
    
    def close(self) -> None:
        """关闭连接"""
        try:
            if self._channel:
                self._channel.close()
            if self._connection:
                self._connection.close()
        except Exception:
            pass
        
        self._available = False
        logger.info("MQ连接已关闭")


class MQConsumer:
    """
    RabbitMQ消息消费者
    
    用于订阅缓存失效消息并执行本地缓存失效
    """
    
    def __init__(
        self,
        config: MQConfig = None,
        cache_manager = None,
    ):
        self.config = config or MQConfig()
        self.cache_manager = cache_manager
        self._connection = None
        self._channel = None
        self._available = False
        self._running = False
        self._consumer_thread = None
        
        self._handlers: Dict[str, Callable] = {}
        self._version_map: Dict[int, int] = {}
    
    def register_handler(
        self,
        message_type: str,
        handler: Callable[[CacheSyncMessage], None]
    ) -> None:
        """注册消息处理器"""
        self._handlers[message_type] = handler
    
    def _init_connection(self) -> bool:
        """初始化连接"""
        try:
            import pika
            
            credentials = pika.PlainCredentials(
                self.config.user,
                self.config.password
            )
            
            self._connection = pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=self.config.host,
                    port=self.config.port,
                    credentials=credentials,
                    virtual_host=self.config.virtual_host,
                    connection_attempts=self.config.retry_attempts,
                    retry_delay=self.config.retry_delay,
                    heartbeat=self.config.heartbeat,
                )
            )
            
            self._channel = self._connection.channel()
            
            self._channel.exchange_declare(
                exchange=self.config.exchange,
                exchange_type=self.config.exchange_type,
                durable=True
            )
            
            result = self._channel.queue_declare(
                queue=self.config.queue_name,
                durable=True
            )
            
            self._channel.queue_bind(
                queue=self.config.queue_name,
                exchange=self.config.exchange,
                routing_key=self.config.routing_key
            )
            
            self._available = True
            logger.info(f"MQ消费者初始化成功: {self.config.queue_name}")
            return True
            
        except Exception as e:
            logger.error(f"MQ消费者初始化失败: {str(e)}")
            self._available = False
            return False
    
    def _on_message(self, channel, method, properties, body) -> None:
        """处理接收到的消息"""
        try:
            message = CacheSyncMessage.from_json(body.decode())
            
            if message.config_id and message.version:
                last_version = self._version_map.get(message.config_id, 0)
                if message.version <= last_version:
                    logger.debug(f"忽略过期消息: {message.message_id}")
                    channel.basic_ack(delivery_tag=method.delivery_tag)
                    return
                
                self._version_map[message.config_id] = message.version
            
            handler = self._handlers.get(message.message_type)
            if handler:
                handler(message)
            else:
                self._default_handler(message)
            
            channel.basic_ack(delivery_tag=method.delivery_tag)
            
        except Exception as e:
            logger.error(f"消息处理失败: {str(e)}")
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
    
    def _default_handler(self, message: CacheSyncMessage) -> None:
        """默认消息处理器"""
        if message.message_type == MessageType.CACHE_INVALIDATE.value:
            self._handle_invalidation(message)
    
    def _handle_invalidation(self, message: CacheSyncMessage) -> None:
        """处理缓存失效消息"""
        if not self.cache_manager:
            return
        
        for key in message.cache_keys:
            self.cache_manager.delete(key)
            logger.debug(f"失效缓存键: {key}")
        
        for pattern in message.patterns:
            self.cache_manager.delete_pattern(pattern)
            logger.debug(f"失效缓存模式: {pattern}")
    
    def start(self) -> bool:
        """启动消费者"""
        if not self._init_connection():
            return False
        
        self._running = True
        
        self._channel.basic_qos(prefetch_count=1)
        self._channel.basic_consume(
            queue=self.config.queue_name,
            on_message_callback=self._on_message
        )
        
        def consume():
            while self._running:
                try:
                    self._connection.process_data_events(time_limit=1)
                except Exception as e:
                    logger.error(f"消费循环错误: {str(e)}")
                    if self._running:
                        time.sleep(5)
                        self._init_connection()
        
        self._consumer_thread = threading.Thread(target=consume, daemon=True)
        self._consumer_thread.start()
        
        logger.info("MQ消费者已启动")
        return True
    
    def stop(self) -> None:
        """停止消费者"""
        self._running = False
        
        try:
            if self._channel:
                self._channel.stop_consuming()
            if self._connection:
                self._connection.close()
        except Exception:
            pass
        
        logger.info("MQ消费者已停止")


class CacheSyncManager:
    """
    缓存同步管理器
    
    统一管理MQ发布者和消费者，提供缓存同步功能
    """
    
    def __init__(
        self,
        mq_config: MQConfig = None,
        cache_manager = None,
        enable_sync: bool = True,
    ):
        self.mq_config = mq_config or MQConfig()
        self.cache_manager = cache_manager
        self.enable_sync = enable_sync
        
        self._publisher: Optional[MQPublisher] = None
        self._consumer: Optional[MQConsumer] = None
        self._mq_available = False
        
        if self.enable_sync:
            self._init_sync()
    
    def _init_sync(self) -> None:
        """初始化同步组件"""
        self._publisher = MQPublisher(self.mq_config)
        self._mq_available = self._publisher.is_available
        
        if self.cache_manager:
            self._consumer = MQConsumer(self.mq_config, self.cache_manager)
    
    @property
    def is_available(self) -> bool:
        """检查MQ同步是否可用"""
        return self._mq_available and self._publisher and self._publisher.is_available
    
    def publish_invalidation(
        self,
        cache_keys: List[str] = None,
        patterns: List[str] = None,
        config_id: int = None,
        config_type: str = None,
        version: int = 0,
        update_type: str = "update",
        source: str = "unknown",
    ) -> bool:
        """发布缓存失效消息"""
        if not self.enable_sync or not self._publisher:
            return False
        
        return self._publisher.publish_invalidation(
            cache_keys=cache_keys,
            patterns=patterns,
            config_id=config_id,
            config_type=config_type,
            version=version,
            update_type=update_type,
            source=source,
        )
    
    def start_consumer(self) -> bool:
        """启动消费者"""
        if not self._consumer:
            return False
        
        return self._consumer.start()
    
    def stop_consumer(self) -> None:
        """停止消费者"""
        if self._consumer:
            self._consumer.stop()
    
    def register_handler(
        self,
        message_type: str,
        handler: Callable[[CacheSyncMessage], None]
    ) -> None:
        """注册消息处理器"""
        if self._consumer:
            self._consumer.register_handler(message_type, handler)
    
    def get_status(self) -> Dict[str, Any]:
        """获取同步状态"""
        return {
            "enabled": self.enable_sync,
            "mq_available": self._mq_available,
            "publisher_available": self._publisher.is_available if self._publisher else False,
            "consumer_running": self._consumer._running if self._consumer else False,
        }
    
    def close(self) -> None:
        """关闭同步管理器"""
        self.stop_consumer()
        if self._publisher:
            self._publisher.close()
