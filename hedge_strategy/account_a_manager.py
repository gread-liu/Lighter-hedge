"""
A账户管理器
负责限价买单的创建和订单状态监控
"""

import sys
import os
import asyncio
import logging
import time
from typing import Optional, Dict, Any

# 添加temp_lighter到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))

import lighter
from redis_messenger import RedisMessenger
from utils import get_orderbook_price_at_depth, parse_price_to_int, calculate_avg_price


class AccountAManager:
    """A账户管理器 - 做多账户"""

    def __init__(
            self,
            signer_client: lighter.SignerClient,
            redis_messenger: RedisMessenger,
            account_index: int,
            market_index: int,
            base_amount: int,
            depth: int,
            poll_interval: int = 1
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
        """
        self.signer_client = signer_client
        self.redis_messenger = redis_messenger
        self.account_index = account_index
        self.market_index = market_index
        self.base_amount = base_amount
        self.depth = depth
        self.poll_interval = poll_interval

        self.current_client_order_index = None
        self.monitoring = False
        self.b_filled_received = False

        logging.info(f"A账户管理器初始化完成: account={account_index}, market={market_index}")

    async def create_limit_buy_order(self) -> bool:
        """
        创建限价买单
        
        Returns:
            是否创建成功
        """
        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                # 检查是否已有活跃订单
                if await self._has_active_orders():
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
                price_int = parse_price_to_int(price_str)

                # 生成client_order_index（使用时间戳+随机数避免冲突）
                # import random
                # client_order_index = int(time.time() * 1000) + random.randint(1, 999)
                client_order_index = 0

                # 创建限价买单
                logging.info(f"创建限价买单: price={price_str}, amount={self.base_amount}")

                tx, resp, err = await self.signer_client.create_order(
                    market_index=self.market_index,
                    client_order_index=client_order_index,
                    base_amount=self.base_amount * 10000,
                    price=price_int,
                    # price=1031263,
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
        收到B账户成交消息的回调
        
        Args:
            message: Redis消息
        """
        logging.info(f"收到B账户成交通知: {message}")
        self.b_filled_received = True

    async def wait_for_b_filled(self, timeout: int = 300):
        """
        等待B账户成交消息
        
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

    def stop_monitoring(self):
        """停止监控"""
        self.monitoring = False
        logging.info("停止订单监控")
