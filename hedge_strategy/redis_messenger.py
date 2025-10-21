"""
Redis消息管理器
使用Pub/Sub模式实现A/B账户之间的消息通信
"""

import json
import logging
import redis
from typing import Callable, Optional, Dict, Any
import threading


class RedisMessenger:
    """Redis消息管理器，基于Pub/Sub模式"""
    
    CHANNEL_A_FILLED = "hedge:account_a_filled"
    CHANNEL_B_FILLED = "hedge:account_b_filled"
    
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0):
        """
        初始化Redis连接
        
        Args:
            host: Redis服务器地址
            port: Redis端口
            db: Redis数据库编号
        """
        self.host = host
        self.port = port
        self.db = db
        self.redis_client = None
        self.pubsub = None
        self.subscriber_thread = None
        self._running = False
        
        logging.info(f"初始化Redis连接: {host}:{port}/{db}")
    
    def connect(self):
        """连接到Redis服务器"""
        try:
            self.redis_client = redis.Redis(
                host=self.host,
                port=self.port,
                db=self.db,
                decode_responses=True
            )
            # 测试连接
            self.redis_client.ping()
            logging.info("Redis连接成功")
        except Exception as e:
            logging.error(f"Redis连接失败: {e}")
            raise
    
    def publish_a_filled(self, message_data: Dict[str, Any]):
        """
        发布A账户成交消息
        
        Args:
            message_data: 消息数据字典
        """
        self._publish(self.CHANNEL_A_FILLED, message_data)
    
    def publish_b_filled(self, message_data: Dict[str, Any]):
        """
        发布B账户成交消息
        
        Args:
            message_data: 消息数据字典
        """
        self._publish(self.CHANNEL_B_FILLED, message_data)
    
    def _publish(self, channel: str, message_data: Dict[str, Any]):
        """
        发布消息到指定channel
        
        Args:
            channel: Redis channel名称
            message_data: 消息数据
        """
        try:
            message_json = json.dumps(message_data)
            self.redis_client.publish(channel, message_json)
            logging.info(f"发布消息到 {channel}: {message_json}")
        except Exception as e:
            logging.error(f"发布消息失败: {e}")
            raise
    
    def subscribe(self, channel: str, callback: Callable[[Dict[str, Any]], None]):
        """
        订阅指定channel并设置回调函数
        
        Args:
            channel: Redis channel名称
            callback: 收到消息时的回调函数
        """
        if self.pubsub is None:
            self.pubsub = self.redis_client.pubsub()
        
        self.pubsub.subscribe(**{channel: self._create_message_handler(callback)})
        logging.info(f"订阅channel: {channel}")
    
    def _create_message_handler(self, callback: Callable[[Dict[str, Any]], None]):
        """
        创建消息处理器
        
        Args:
            callback: 用户定义的回调函数
        
        Returns:
            消息处理函数
        """
        def handler(message):
            try:
                if message['type'] == 'message':
                    data = json.loads(message['data'])
                    logging.info(f"收到消息: {data}")
                    callback(data)
            except Exception as e:
                logging.error(f"处理消息失败: {e}")
        
        return handler
    
    def start_listening(self):
        """启动监听线程"""
        if self.pubsub is None:
            logging.warning("未订阅任何channel，无法启动监听")
            return
        
        self._running = True
        self.subscriber_thread = self.pubsub.run_in_thread(sleep_time=0.01, daemon=True)
        logging.info("Redis监听线程已启动")
    
    def stop_listening(self):
        """停止监听"""
        self._running = False
        if self.subscriber_thread:
            self.subscriber_thread.stop()
            logging.info("Redis监听线程已停止")
    
    def close(self):
        """关闭Redis连接"""
        self.stop_listening()
        if self.pubsub:
            self.pubsub.close()
        if self.redis_client:
            self.redis_client.close()
        logging.info("Redis连接已关闭")
    
    @staticmethod
    def create_filled_message(
        account_index: int,
        market_index: int,
        order_index: int,
        filled_base_amount: str,
        filled_quote_amount: str,
        avg_price: str,
        side: str
    ) -> Dict[str, Any]:
        """
        创建标准格式的成交消息
        
        Args:
            account_index: 账户索引
            market_index: 市场索引
            order_index: 订单索引
            filled_base_amount: 成交基础资产数量
            filled_quote_amount: 成交计价资产数量
            avg_price: 平均成交价格
            side: 方向 ("buy" 或 "sell")
        
        Returns:
            消息字典
        """
        import time
        return {
            "account_index": account_index,
            "market_index": market_index,
            "order_index": order_index,
            "filled_base_amount": filled_base_amount,
            "filled_quote_amount": filled_quote_amount,
            "avg_price": avg_price,
            "timestamp": int(time.time()),
            "side": side
        }

