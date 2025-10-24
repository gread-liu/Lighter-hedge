"""
A账户管理器
负责限价买单的创建和订单状态监控
支持WebSocket实时监听订单成交
"""

import asyncio
import logging
import os
import sys
import time
import threading
from decimal import Decimal
from typing import Dict, Any, Optional

# 添加temp_lighter到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))

import lighter
from lighter import WsClient
from redis_messenger import RedisMessenger
from utils import get_orderbook_price_at_depth, calculate_avg_price


class AccountAManager:
    """A账户管理器 - 做多账户，支持WebSocket实时监听订单成交"""

    def __init__(
            self,
            signer_client: lighter.SignerClient,
            redis_messenger: RedisMessenger,
            account_index: int,
            market_index: int,
            base_amount: int,
            depth: int,
            poll_interval: int = 1,
            ws_url: Optional[str] = None
    ):
        """
        初始化A账户管理器
        
        Args:
            signer_client: lighter签名客户端
            redis_messenger: Redis消息管理器
            account_index: 账户索引
            market_index: 市场索引
            base_amount: 挂单数量
            depth: 挂单档位
            poll_interval: 轮询间隔（秒）
            ws_url: WebSocket服务器地址（可选）
        """
        self.signer_client = signer_client
        self.redis_messenger = redis_messenger
        self.account_index = account_index
        self.market_index = market_index
        self.base_amount = base_amount
        self.depth = depth
        self.poll_interval = poll_interval
        self.ws_url = ws_url

        self.current_client_order_index = None
        self.current_order_index = None  # 系统分配的订单索引
        self.monitoring = False
        self.b_filled_received = False
        self.b_hedge_confirmed = False  # B账户对冲确认标志
        self.b_hedge_failed = False  # B账户对冲失败标志
        self.pause_trading = False  # 暂停交易标志
        
        # WebSocket相关
        self.ws_client: Optional[WsClient] = None
        self.ws_thread: Optional[threading.Thread] = None
        self.ws_heartbeat_thread: Optional[threading.Thread] = None
        self.ws_running = False
        self.pending_orders = {}  # 跟踪待成交订单 {order_index: order_info}
        self.last_ws_message_time = time.time()  # 最后收到消息的时间

        logging.info(f"A账户管理器初始化完成: account={account_index}, market={market_index}")

    async def create_limit_buy_order(self, base_amount_multiplier, price_multiplier, active_orders=None) -> bool:
        """
        创建限价买单
        
        Args:
            base_amount_multiplier: 基础数量乘数
            price_multiplier: 价格乘数
            active_orders: 活跃订单列表（可选，如果提供则不再查询）
        
        Returns:
            是否创建成功
        """
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                # 检查是否已有活跃订单（如果已提供active_orders，直接使用）
                if active_orders is None:
                    if await self._has_active_orders():
                        logging.info("A账户已有活跃订单，跳过创建")
                        return False
                elif len(active_orders) > 0:
                    logging.info("A账户已有活跃订单，跳过创建")
                    return False

                # 获取买N档价格
                price_str = await get_orderbook_price_at_depth(
                    self.signer_client.api_client,
                    self.market_index,
                    self.depth,
                    is_bid=True
                )

                if price_str is None:
                    logging.error("无法获取订单簿价格")
                    return False

                # 转换价格为整数格式
                price_dec = Decimal(price_str)

                # 生成client_order_index（使用时间戳+随机数避免冲突）
                # import random
                # client_order_index = int(time.time() * 1000) + random.randint(1, 999)
                client_order_index = 0

                # 创建限价买单
                logging.info(f"创建限价买单: price={price_str}, amount={self.base_amount}")

                tx, resp, err = await self.signer_client.create_order(
                    market_index=self.market_index,
                    client_order_index=client_order_index,
                    base_amount=int(self.base_amount * base_amount_multiplier),
                    price=int(price_dec * price_multiplier),
                    is_ask=False,  # 买单
                    order_type=lighter.SignerClient.ORDER_TYPE_LIMIT,
                    time_in_force=lighter.SignerClient.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                    reduce_only=False,
                    trigger_price=0
                )

                if err:
                    # 检查是否是nonce错误
                    if "invalid nonce" in str(err).lower():
                        logging.warning(f"Nonce错误，刷新nonce管理器后重试 (尝试 {retry_count + 1}/{max_retries})")
                        # 强制刷新nonce
                        self.signer_client.nonce_manager.hard_refresh_nonce(self.signer_client.api_key_index)
                        retry_count += 1
                        await asyncio.sleep(1)  # 短暂等待
                        continue
                    else:
                        logging.error(f"创建订单失败: {err}")
                        return False

                if resp.code != 200:
                    logging.error(f"创建订单失败: code={resp.code}, msg={resp.message}")
                    return False

                # 记录客户端订单索引 - order_index由系统分配，我们使用client_order_index跟踪
                self.current_client_order_index = client_order_index
                logging.info(f"限价买单创建成功: client_order_index={client_order_index}, tx_hash={resp.tx_hash}")
                
                # 查询订单获取order_index（系统分配的）
                await asyncio.sleep(1)  # 等待订单上链
                order_info = await self._get_order_by_client_index(client_order_index)
                if order_info:
                    self.current_order_index = order_info.order_index
                    # 添加到待成交订单列表
                    self.pending_orders[self.current_order_index] = {
                        'client_order_index': client_order_index,
                        'side': 'buy',
                        'initial_amount': order_info.initial_base_amount,
                        'price': price_str
                    }
                    logging.info(f"订单已添加到监控列表: order_index={self.current_order_index}")

                return True

            except Exception as e:
                if "invalid nonce" in str(e).lower():
                    logging.warning(f"Nonce异常，刷新nonce管理器后重试 (尝试 {retry_count + 1}/{max_retries}): {e}")
                    # 强制刷新nonce
                    self.signer_client.nonce_manager.hard_refresh_nonce(self.signer_client.api_key_index)
                    retry_count += 1
                    await asyncio.sleep(1)  # 短暂等待
                    continue
                else:
                    logging.error(f"创建限价买单异常: {e}")
                    return False

        logging.error(f"创建限价买单失败，已重试{max_retries}次")
        return False

    async def create_limit_sell_order(self, base_amount_multiplier, price_multiplier, active_orders=None) -> bool:
        """
        创建限价卖单
        
        Args:
            base_amount_multiplier: 基础数量乘数
            price_multiplier: 价格乘数
            active_orders: 活跃订单列表（可选，如果提供则不再查询）

        Returns:
            是否创建成功
        """
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                # 检查是否已有活跃订单（如果已提供active_orders，直接使用）
                if active_orders is None:
                    if await self._has_active_orders():
                        logging.info("A账户已有活跃订单，跳过创建")
                        return False
                elif len(active_orders) > 0:
                    logging.info("A账户已有活跃订单，跳过创建")
                    return False

                # 获取卖N档价格
                price_str = await get_orderbook_price_at_depth(
                    self.signer_client.api_client,
                    self.market_index,
                    self.depth,
                    is_bid=False
                )

                if price_str is None:
                    logging.error("无法获取订单簿价格")
                    return False

                # 转换价格为整数格式
                price_dec = Decimal(price_str)

                # 生成client_order_index（使用时间戳+随机数避免冲突）
                # import random
                # client_order_index = int(time.time() * 1000) + random.randint(1, 999)
                client_order_index = 0

                # 创建限价买单
                logging.info(f"创建限价卖单: price={price_str}, amount={self.base_amount}")

                tx, resp, err = await self.signer_client.create_order(
                    market_index=self.market_index,
                    client_order_index=client_order_index,
                    base_amount=int(self.base_amount * base_amount_multiplier),
                    price=int(price_dec * price_multiplier),
                    is_ask=True,  # 买单
                    order_type=lighter.SignerClient.ORDER_TYPE_LIMIT,
                    time_in_force=lighter.SignerClient.ORDER_TIME_IN_FORCE_GOOD_TILL_TIME,
                    reduce_only=False,
                    trigger_price=0
                )

                if err:
                    # 检查是否是nonce错误
                    if "invalid nonce" in str(err).lower():
                        logging.warning(f"Nonce错误，刷新nonce管理器后重试 (尝试 {retry_count + 1}/{max_retries})")
                        # 强制刷新nonce
                        self.signer_client.nonce_manager.hard_refresh_nonce(self.signer_client.api_key_index)
                        retry_count += 1
                        await asyncio.sleep(1)  # 短暂等待
                        continue
                    else:
                        logging.error(f"创建订单失败: {err}")
                        return False

                if resp.code != 200:
                    logging.error(f"创建订单失败: code={resp.code}, msg={resp.message}")
                    return False

                # 记录客户端订单索引 - order_index由系统分配，我们使用client_order_index跟踪
                self.current_client_order_index = client_order_index
                logging.info(f"限价卖单创建成功: client_order_index={client_order_index}, tx_hash={resp.tx_hash}")
                
                # 查询订单获取order_index（系统分配的）
                await asyncio.sleep(1)  # 等待订单上链
                order_info = await self._get_order_by_client_index(client_order_index)
                if order_info:
                    self.current_order_index = order_info.order_index
                    # 添加到待成交订单列表
                    self.pending_orders[self.current_order_index] = {
                        'client_order_index': client_order_index,
                        'side': 'sell',
                        'initial_amount': order_info.initial_base_amount,
                        'price': price_str
                    }
                    logging.info(f"订单已添加到监控列表: order_index={self.current_order_index}")

                return True

            except Exception as e:
                if "invalid nonce" in str(e).lower():
                    logging.warning(f"Nonce异常，刷新nonce管理器后重试 (尝试 {retry_count + 1}/{max_retries}): {e}")
                    # 强制刷新nonce
                    self.signer_client.nonce_manager.hard_refresh_nonce(self.signer_client.api_key_index)
                    retry_count += 1
                    await asyncio.sleep(1)  # 短暂等待
                    continue
                else:
                    logging.error(f"创建限价买单异常: {e}")
                    return False

        logging.error(f"创建限价买单失败，已重试{max_retries}次")
        return False

    async def _get_order_by_client_index(self, client_order_index: int):
        """
        根据client_order_index查询订单信息
        
        Args:
            client_order_index: 客户端订单索引
            
        Returns:
            订单对象或None
        """
        try:
            # 生成认证token
            auth_token, auth_error = self.signer_client.create_auth_token_with_expiry()
            if auth_error:
                logging.error(f"生成认证token失败: {auth_error}")
                return None

            order_api = lighter.OrderApi(self.signer_client.api_client)
            
            # 先查询活跃订单
            orders = await order_api.account_active_orders(
                account_index=self.account_index,
                market_id=self.market_index,
                auth=auth_token
            )
            
            if orders.orders:
                for order in orders.orders:
                    if order.client_order_index == client_order_index:
                        return order
            
            # 如果活跃订单中没有，查询非活跃订单
            # 重新生成认证token
            auth_token, auth_error = self.signer_client.create_auth_token_with_expiry()
            if auth_error:
                logging.error(f"生成认证token失败: {auth_error}")
                return None
            
            inactive_orders = await order_api.account_inactive_orders(
                account_index=self.account_index,
                market_id=self.market_index,
                limit=10,
                auth=auth_token
            )
            
            if inactive_orders.orders:
                for order in inactive_orders.orders:
                    if order.client_order_index == client_order_index:
                        return order
            
            return None
            
        except Exception as e:
            logging.error(f"查询订单失败: {e}")
            return None

    async def _has_active_orders(self) -> bool:
        """
        检查是否有活跃订单
        
        Returns:
            是否有活跃订单
        """
        try:
            # 生成认证token
            auth_token, auth_error = self.signer_client.create_auth_token_with_expiry()
            if auth_error:
                logging.error(f"生成认证token失败: {auth_error}")
                return False

            order_api = lighter.OrderApi(self.signer_client.api_client)
            orders = await order_api.account_active_orders(
                account_index=self.account_index,
                market_id=self.market_index,
                auth=auth_token
            )

            return orders.orders and len(orders.orders) > 0
        except Exception as e:
            logging.error(f"查询活跃订单失败: {e}")
            return False

    async def monitor_order_until_filled(self):
        """
        监控订单直到完全成交
        使用轮询方式检查订单状态
        """
        if self.current_client_order_index is None:
            logging.error("没有需要监控的订单")
            return

        self.monitoring = True
        logging.info(f"开始监控订单: client_order_index={self.current_client_order_index}")

        order_api = lighter.OrderApi(self.signer_client.api_client)

        while self.monitoring:
            try:
                # 生成认证token（增加重试机制）
                auth_token = None
                for auth_retry in range(3):
                    auth_token, auth_error = self.signer_client.create_auth_token_with_expiry()
                    if auth_error is None:
                        break
                    logging.warning(f"生成认证token失败 (尝试 {auth_retry + 1}/3): {auth_error}")
                    await asyncio.sleep(0.5)

                if auth_token is None:
                    logging.error("无法生成认证token，跳过本次监控")
                    await asyncio.sleep(self.poll_interval)
                    continue

                # 查询活跃订单
                orders = await order_api.account_active_orders(
                    account_index=self.account_index,
                    market_id=self.market_index,
                    auth=auth_token
                )

                # 查找当前订单 - 使用client_order_index
                current_order = None
                if orders.orders:
                    for order in orders.orders:
                        if order.client_order_index == self.current_client_order_index:
                            current_order = order
                            break

                # 如果订单不在活跃列表中，可能已经完全成交或取消
                if current_order is None:
                    # 查询非活跃订单确认
                    inactive_orders = await order_api.account_inactive_orders(
                        account_index=self.account_index,
                        market_id=self.market_index,
                        limit=10
                    )

                    if inactive_orders.orders:
                        for order in inactive_orders.orders:
                            if order.client_order_index == self.current_client_order_index:
                                current_order = order
                                break

                # 检查订单状态
                if current_order:
                    status = current_order.status
                    filled_amount = current_order.filled_base_amount
                    initial_amount = current_order.initial_base_amount

                    logging.info(f"订单状态: {status}, 成交量: {filled_amount}/{initial_amount}")

                    # 判断是否完全成交
                    if status == "filled" and filled_amount == initial_amount:
                        logging.info("订单完全成交！")

                        # 发送Redis消息
                        await self._notify_order_filled(current_order)

                        self.monitoring = False
                        break
                    elif status.startswith("canceled"):
                        logging.warning(f"订单已取消: {status}")
                        self.monitoring = False
                        break

                # 等待下一次轮询
                await asyncio.sleep(self.poll_interval)

            except Exception as e:
                logging.error(f"监控订单异常: {e}")
                await asyncio.sleep(self.poll_interval)

    async def _notify_order_filled(self, order):
        """
        通知订单完全成交
        
        Args:
            order: 订单对象
        """
        try:
            # 计算平均价格
            avg_price = calculate_avg_price(
                order.filled_base_amount,
                order.filled_quote_amount
            )

            # 创建消息
            message = RedisMessenger.create_filled_message(
                account_index=self.account_index,
                market_index=self.market_index,
                order_index=order.order_index,
                filled_base_amount=order.filled_base_amount,
                filled_quote_amount=order.filled_quote_amount,
                avg_price=avg_price,
                side="buy"
            )

            # 发布到Redis
            self.redis_messenger.publish_a_filled(message)
            logging.info("已发送A账户成交通知到Redis")

        except Exception as e:
            logging.error(f"发送成交通知失败: {e}")
            raise

    def on_b_account_filled(self, message: Dict[str, Any]):
        """
        收到B账户对冲结果消息的回调（成功或失败）
        
        Args:
            message: Redis消息，包含status字段（"success"或"failed"）
        """
        status = message.get("status", "success")  # 默认为成功
        
        if status == "success":
            logging.info(f"✅ 收到B账户对冲成功通知: {message}")
            self.b_filled_received = True
            self.b_hedge_confirmed = True
            self.b_hedge_failed = False
        else:  # status == "failed"
            logging.error(f"❌ 收到B账户对冲失败通知: {message}")
            self.b_hedge_failed = True
            self.b_hedge_confirmed = False
            self.pause_trading = True  # 暂停交易，等待人工处理
            logging.error("⚠️ 交易已暂停，请人工检查并处理B账户对冲失败问题！")

    async def wait_for_b_filled(self, timeout: int = 300):
        """
        等待B账户成交消息（旧方法，保留兼容性）
        
        Args:
            timeout: 超时时间（秒）
        """
        logging.info("等待B账户成交通知...")
        self.b_filled_received = False

        start_time = time.time()
        while not self.b_filled_received:
            await asyncio.sleep(0.5)

            # 检查超时
            if time.time() - start_time > timeout:
                logging.error("等待B账户成交超时")
                raise TimeoutError("等待B账户成交超时")

        logging.info("B账户成交确认，准备继续挂单")
    
    async def wait_for_b_hedge_confirmation(self, timeout: int = 60):
        """
        等待B账户对冲确认（成功或失败）
        
        Args:
            timeout: 超时时间（秒），默认60秒
            
        Raises:
            TimeoutError: 超时未收到确认
            Exception: B账户对冲失败
        """
        logging.info("⏳ 等待B账户对冲确认...")
        self.b_hedge_confirmed = False
        self.b_hedge_failed = False
        
        start_time = time.time()
        while not self.b_hedge_confirmed and not self.b_hedge_failed:
            await asyncio.sleep(0.5)
            
            # 检查超时
            elapsed_time = time.time() - start_time
            if elapsed_time > timeout:
                logging.error(f"❌ 等待B账户对冲确认超时（{timeout}秒）")
                raise TimeoutError(f"等待B账户对冲确认超时（{timeout}秒）")
            
            # 每10秒输出一次等待状态
            if int(elapsed_time) % 10 == 0 and int(elapsed_time) > 0:
                logging.info(f"⏳ 仍在等待B账户对冲确认... ({int(elapsed_time)}秒)")
        
        # 检查结果
        if self.b_hedge_failed:
            error_msg = "B账户对冲失败，交易已暂停！请人工检查并处理！"
            logging.error(f"❌ {error_msg}")
            raise Exception(error_msg)
        
        if self.b_hedge_confirmed:
            logging.info("✅ B账户对冲确认成功，可以继续交易")

    def start_ws_monitoring(self):
        """启动WebSocket监听"""
        if self.ws_running:
            logging.warning("WebSocket监听已在运行")
            return
        
        try:
            logging.info(f"启动WebSocket监听账户: {self.account_index}")
            
            # 创建WebSocket客户端
            self.ws_client = WsClient(
                host=self.ws_url,
                account_ids=[self.account_index],
                on_account_update=self._on_account_update
            )
            
            # 在单独线程中运行WebSocket
            self.ws_running = True
            self.last_ws_message_time = time.time()
            
            self.ws_thread = threading.Thread(
                target=self._run_ws_client,
                daemon=True
            )
            self.ws_thread.start()
            
            # 启动心跳线程
            self.ws_heartbeat_thread = threading.Thread(
                target=self._ws_heartbeat_monitor,
                daemon=True
            )
            self.ws_heartbeat_thread.start()
            
            logging.info("WebSocket监听和心跳监控已启动")
            
        except Exception as e:
            logging.error(f"启动WebSocket监听失败: {e}")
            self.ws_running = False
    
    def _run_ws_client(self):
        """在线程中运行WebSocket客户端，支持断线重连和指数退避"""
        base_retry_interval = 2  # 基础重试间隔（秒）
        max_retry_interval = 60  # 最大重试间隔（秒）
        current_retry_interval = base_retry_interval
        consecutive_failures = 0  # 连续失败次数
        
        while self.ws_running:
            try:
                logging.info("WebSocket开始连接...")
                self.ws_client.run()
                
                # 如果run()正常退出，说明连接被关闭
                if self.ws_running:
                    consecutive_failures += 1
                    
                    # 使用指数退避策略
                    if consecutive_failures > 1:
                        current_retry_interval = min(
                            base_retry_interval * (2 ** (consecutive_failures - 1)),
                            max_retry_interval
                        )
                    else:
                        current_retry_interval = base_retry_interval
                    
                    logging.warning(
                        f"WebSocket连接断开（连续失败{consecutive_failures}次），"
                        f"{current_retry_interval}秒后重试..."
                    )
                    time.sleep(current_retry_interval)
                    
                    # 重新创建WebSocket客户端
                    try:
                        self.ws_client = WsClient(
                            host=self.ws_url,
                            account_ids=[self.account_index],
                            on_account_update=self._on_account_update
                        )
                    except Exception as create_error:
                        logging.error(f"重新创建WebSocket客户端失败: {create_error}")
                        continue
                else:
                    # ws_running=False，正常退出
                    break
                    
            except Exception as e:
                if self.ws_running:
                    consecutive_failures += 1
                    
                    # 使用指数退避策略
                    if consecutive_failures > 1:
                        current_retry_interval = min(
                            base_retry_interval * (2 ** (consecutive_failures - 1)),
                            max_retry_interval
                        )
                    else:
                        current_retry_interval = base_retry_interval
                    
                    logging.error(
                        f"WebSocket运行异常: {e}（连续失败{consecutive_failures}次），"
                        f"{current_retry_interval}秒后重试..."
                    )
                    time.sleep(current_retry_interval)
                    
                    # 重新创建WebSocket客户端
                    try:
                        self.ws_client = WsClient(
                            host=self.ws_url,
                            account_ids=[self.account_index],
                            on_account_update=self._on_account_update
                        )
                    except Exception as create_error:
                        logging.error(f"重新创建WebSocket客户端失败: {create_error}")
                        continue
                else:
                    # ws_running=False，正常退出
                    break
            
            # 如果成功运行了一段时间后断开，重置失败计数
            if consecutive_failures > 0:
                logging.info("WebSocket连接已恢复，重置失败计数")
                consecutive_failures = 0
                current_retry_interval = base_retry_interval
        
        logging.info("WebSocket监听线程退出")
    
    def _on_account_update(self, account_id: str, account_data: Dict[str, Any]):
        """
        WebSocket账户更新回调
        
        Args:
            account_id: 账户ID
            account_data: 账户数据
        """
        try:
            # 更新最后收到消息的时间
            self.last_ws_message_time = time.time()
            
            # 处理ping消息 - 主动回复pong保持连接
            if isinstance(account_data, dict) and account_data.get('type') == 'ping':
                logging.debug("收到WebSocket ping消息，回复pong")
                try:
                    # 发送pong响应
                    if self.ws_client and self.ws_client.ws:
                        import json
                        pong_message = json.dumps({"type": "pong"})
                        self.ws_client.ws.send(pong_message)
                        logging.debug("已发送pong响应")
                except Exception as pong_err:
                    logging.warning(f"发送pong响应失败: {pong_err}")
                return
            
            if not isinstance(account_data, dict):
                return
            
            # 检查是否有交易记录（trades字段表示订单成交）
            trades = account_data.get('trades', {})
            if trades and str(self.market_index) in trades:
                market_trades = trades[str(self.market_index)]
                logging.debug(f"收到{len(market_trades)}笔交易记录")
                
                for trade in market_trades:
                    # 检查是否是我们的订单成交
                    # 如果是maker，检查ask_id或bid_id
                    ask_id = trade.get('ask_id')
                    bid_id = trade.get('bid_id')
                    is_maker_ask = trade.get('is_maker_ask')
                    
                    # 确定是哪个订单成交了
                    order_index = None
                    side = None
                    is_limit_order = False  # 标记是否是限价单
                    
                    # 从pending_orders中查找(只有限价单会在pending_orders中)
                    if is_maker_ask and ask_id in self.pending_orders:
                        order_index = ask_id
                        side = self.pending_orders[ask_id]['side']
                        is_limit_order = True
                    elif not is_maker_ask and bid_id in self.pending_orders:
                        order_index = bid_id
                        side = self.pending_orders[bid_id]['side']
                        is_limit_order = True
                    else:
                        # 如果pending_orders中没有,说明是市价单(紧急平仓等)
                        # 市价单不需要通知B账户,直接跳过
                        if is_maker_ask:
                            order_index = ask_id
                        else:
                            order_index = bid_id
                        
                        logging.info(f"订单{order_index}成交(市价单),不发送Redis通知")
                        continue  # 跳过市价单,不发送通知
                    
                    if order_index and is_limit_order:
                        logging.info(f"✅ 限价单完全成交！order_index={order_index}")
                        
                        # 从交易记录中获取成交信息
                        size = trade.get('size', '0')
                        price = trade.get('price', '0')
                        usd_amount = trade.get('usd_amount', '0')
                        
                        logging.info(f"成交详情: size={size}, price={price}, usd_amount={usd_amount}")
                        logging.info(f"准备发送Redis通知: order_index={order_index}, side={side}, avg_price={price}")
                        
                        # 只对限价单发送Redis通知
                        self._notify_order_filled_ws_sync(
                            order_index=order_index,
                            filled_base_amount=size,
                            filled_quote_amount=usd_amount,
                            avg_price=price,
                            side=side
                        )
                        
                        # 从待成交列表中移除
                        if order_index in self.pending_orders:
                            del self.pending_orders[order_index]
                            logging.info(f"订单{order_index}已从监控列表移除")
            else:
                # 如果没有trades字段，记录调试信息
                if 'orders' not in account_data and 'trades' not in account_data:
                    logging.debug(f"WebSocket消息不包含orders或trades字段")
                        
        except Exception as e:
            logging.error(f"处理账户更新异常: {e}", exc_info=True)
    
    def _notify_order_filled_ws_sync(
        self,
        order_index: int,
        filled_base_amount: str,
        filled_quote_amount: str,
        avg_price: str,
        side: str
    ):
        """
        通过WebSocket收到成交后发送Redis通知（同步版本）
        
        Args:
            order_index: 订单索引
            filled_base_amount: 成交数量
            filled_quote_amount: 成交金额
            avg_price: 平均价格
            side: 订单方向
        """
        try:
            # 创建消息
            message = RedisMessenger.create_filled_message(
                account_index=self.account_index,
                market_index=self.market_index,
                order_index=order_index,
                filled_base_amount=filled_base_amount,
                filled_quote_amount=filled_quote_amount,
                avg_price=avg_price,
                side=side
            )
            
            # 发布到Redis（同步调用）
            self.redis_messenger.publish_a_filled(message)
            logging.info(f"已通过WebSocket发送A账户成交通知到Redis: order_index={order_index}")
            
        except Exception as e:
            logging.error(f"发送WebSocket成交通知失败: {e}")

    def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
        logging.info("停止订单监控")
    
    def _ws_heartbeat_monitor(self):
        """WebSocket心跳监控线程"""
        heartbeat_interval = 30  # 心跳间隔（秒）
        timeout_threshold = 90  # 超时阈值（秒）
        
        logging.info(f"WebSocket心跳监控已启动: 间隔={heartbeat_interval}s, 超时阈值={timeout_threshold}s")
        
        while self.ws_running:
            try:
                time.sleep(heartbeat_interval)
                
                if not self.ws_running:
                    break
                
                # 检查距离上次收到消息的时间
                time_since_last_message = time.time() - self.last_ws_message_time
                
                if time_since_last_message > timeout_threshold:
                    logging.warning(
                        f"WebSocket连接可能已断开（{time_since_last_message:.1f}秒未收到消息），"
                        f"尝试重新连接..."
                    )
                    # 关闭当前连接，触发重连
                    try:
                        if self.ws_client and self.ws_client.ws:
                            self.ws_client.ws.close()
                    except Exception as close_err:
                        logging.debug(f"关闭WebSocket连接时出错: {close_err}")
                else:
                    logging.debug(
                        f"WebSocket心跳检查: 距上次消息 {time_since_last_message:.1f}秒"
                    )
                    
            except Exception as e:
                logging.error(f"心跳监控异常: {e}")
                if not self.ws_running:
                    break
        
        logging.info("WebSocket心跳监控线程退出")
    
    def stop_ws_monitoring(self):
        """停止WebSocket监听"""
        if not self.ws_running:
            return
        
        try:
            self.ws_running = False
            
            # 停止WebSocket客户端
            if self.ws_client and self.ws_client.ws:
                self.ws_client.ws.close()
            
            # 等待线程退出
            if self.ws_thread:
                self.ws_thread.join(timeout=5)
            if self.ws_heartbeat_thread:
                self.ws_heartbeat_thread.join(timeout=5)
                
            logging.info("WebSocket监听和心跳监控已停止")
        except Exception as e:
            logging.error(f"停止WebSocket监听失败: {e}")
