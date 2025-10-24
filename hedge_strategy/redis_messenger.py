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
    
    CHANNEL_A_FILLED = "hedge:account_a_filled"  # 默认值，将被动态设置
    CHANNEL_B_FILLED = "hedge:account_b_filled"
    POSITIONS_KEY_PREFIX = "hedge:positions"  # 持仓key前缀
    
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0,
                 account_a_name: str = None, account_b_name: str = None):
        """
        初始化Redis连接
        
        Args:
            host: Redis服务器地址
            port: Redis端口
            db: Redis数据库编号
            account_a_name: A账户名称（用于构建channel和key名称）
            account_b_name: B账户名称（用于构建channel和key名称）
        """
        self.host = host
        self.port = port
        self.db = db
        self.redis_client = None
        self.pubsub = None
        self.subscriber_thread = None
        self._running = False
        
        # 保存账户名称用于构建key
        self.account_a_name = account_a_name
        self.account_b_name = account_b_name
        
        # 动态设置channel名称
        if account_a_name and account_b_name:
            self.CHANNEL_A_FILLED = f"hedge:{account_a_name}_to_{account_b_name}"
            logging.info(f"使用自定义channel: {self.CHANNEL_A_FILLED}")
        else:
            logging.info(f"使用默认channel: {self.CHANNEL_A_FILLED}")
        
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
        发布B账户对冲结果消息（成功或失败）
        
        Args:
            message_data: 消息数据字典，包含status字段（"success"或"failed"）
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
    
    def update_position(self, account_name: str, account_index: int, market: str,
                       position_size: float, sign: int, available_balance: str = None):
        """
        更新账户持仓到Redis
        
        新的Hash结构：
        - Key: hedge:positions:{account_a_name}_{account_b_name}:{market}
        - 例如: hedge:positions:account_4_account_5:BTC
        - Type: Hash
        - Fields:
          - {account_name}: JSON字符串,包含该账户的持仓信息
        
        数据结构示例:
        {
          "account_name": "account_4",
          "account_index": 280459,
          "size": 0.0002,
          "sign": 1,
          "direction": "long",
          "timestamp": 1761290287,
          "market": "BTC",
          "available_balance": "25.631906"
        }
        
        智能时间戳逻辑：
        - 如果持仓大小和方向都没变，保留原时间戳（仓位创建时间）
        - 如果持仓发生变化，更新时间戳为当前时间
        
        Args:
            account_name: 账户名称 (例如: "account_4", "account_5")
            account_index: 账户索引
            market: 市场名称 ("BTC" 或 "ETH")
            position_size: 持仓大小
            sign: 持仓方向 (1=多头, -1=空头)
            available_balance: 可用余额 (可选)
        """
        try:
            import time
            from decimal import Decimal
            
            # 转换Decimal为float
            if isinstance(position_size, Decimal):
                position_size = float(position_size)
            
            # 构建Redis key: hedge:positions:account_4_account_5:BTC
            if self.account_a_name and self.account_b_name:
                redis_key = f"{self.POSITIONS_KEY_PREFIX}:{self.account_a_name}_{self.account_b_name}:{market.upper()}"
            else:
                # 向后兼容
                redis_key = f"{self.POSITIONS_KEY_PREFIX}:{market.upper()}"
            
            # 获取现有持仓数据
            existing_position = self.get_position_by_account_name(account_name, market)
            
            # 判断持仓是否发生变化
            if existing_position:
                existing_size = existing_position.get("size", 0)
                existing_sign = existing_position.get("sign", 0)
                existing_timestamp = existing_position.get("timestamp", int(time.time()))
                
                # 如果持仓大小和方向都没变，保留原时间戳
                if existing_size == position_size and existing_sign == sign:
                    timestamp = existing_timestamp
                else:
                    # 持仓发生变化，更新时间戳
                    timestamp = int(time.time())
            else:
                # 首次创建持仓记录
                timestamp = int(time.time())
            
            # 构建持仓数据
            position_dict = {
                "account_name": account_name,
                "account_index": account_index,
                "size": position_size,
                "sign": sign,
                "direction": "long" if sign == 1 else "short" if sign == -1 else "none",
                "timestamp": timestamp,
                "market": market.upper()
            }
            
            # 如果提供了可用余额,添加到数据中
            if available_balance is not None:
                position_dict["available_balance"] = available_balance
            
            position_data = json.dumps(position_dict)
            
            # 使用Hash结构存储: HSET hedge:positions:BTC account_4 {...}
            self.redis_client.hset(redis_key, account_name, position_data)
            logging.debug(f"更新持仓到Redis: HSET {redis_key} {account_name} = {position_data}")
        except Exception as e:
            logging.error(f"更新持仓到Redis失败: {e}")
    
    def get_position_by_account_name(self, account_name: str, market: str) -> Optional[Dict[str, Any]]:
        """
        从Redis获取指定账户的持仓
        
        Args:
            account_name: 账户名称 (例如: "account_4", "account_5")
            market: 市场名称 ("BTC" 或 "ETH")
        
        Returns:
            持仓数据字典或None
        """
        try:
            # 构建Redis key: hedge:positions:account_4_account_5:BTC
            if self.account_a_name and self.account_b_name:
                redis_key = f"{self.POSITIONS_KEY_PREFIX}:{self.account_a_name}_{self.account_b_name}:{market.upper()}"
            else:
                # 向后兼容
                redis_key = f"{self.POSITIONS_KEY_PREFIX}:{market.upper()}"
            
            position_json = self.redis_client.hget(redis_key, account_name)
            if position_json:
                return json.loads(position_json)
            return None
        except Exception as e:
            logging.error(f"从Redis获取持仓失败: {e}")
            return None
    
    def get_position(self, account: str, market: str) -> Optional[Dict[str, Any]]:
        """
        从Redis获取账户持仓 (兼容旧接口)
        
        Args:
            account: 账户标识 ("account_a" 或 "account_b")
            market: 市场名称 ("BTC" 或 "ETH")
        
        Returns:
            持仓数据字典或None
        """
        # 这个方法保留用于向后兼容,但实际使用account_name
        # 需要从配置中获取account_name,这里暂时返回None
        logging.warning(f"get_position方法已废弃,请使用get_position_by_account_name")
        return None
    
    def get_all_positions(self, market: str) -> Dict[str, Any]:
        """
        获取指定市场的所有账户持仓
        
        Args:
            market: 市场名称 ("BTC" 或 "ETH")
        
        Returns:
            所有持仓数据字典,key为account_name
        """
        try:
            # 构建Redis key: hedge:positions:account_4_account_5:BTC
            if self.account_a_name and self.account_b_name:
                redis_key = f"{self.POSITIONS_KEY_PREFIX}:{self.account_a_name}_{self.account_b_name}:{market.upper()}"
            else:
                # 向后兼容
                redis_key = f"{self.POSITIONS_KEY_PREFIX}:{market.upper()}"
            
            # 获取Hash中的所有字段
            all_positions = self.redis_client.hgetall(redis_key)
            result = {}
            for account_name, position_json in all_positions.items():
                result[account_name] = json.loads(position_json)
            return result
        except Exception as e:
            logging.error(f"从Redis获取所有持仓失败: {e}")
            return {}

