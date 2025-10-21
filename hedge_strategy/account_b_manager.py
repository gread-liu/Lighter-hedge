"""
B账户管理器
负责市价卖单对冲
"""

import sys
import os
import asyncio
import logging
import time
from typing import Dict, Any

# 添加temp_lighter到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))

import lighter
from redis_messenger import RedisMessenger
from utils import calculate_avg_price


class AccountBManager:
    """B账户管理器 - 做空账户"""
    
    def __init__(
        self,
        signer_client: lighter.SignerClient,
        redis_messenger: RedisMessenger,
        account_index: int,
        retry_times: int = 3
    ):
        """
        初始化B账户管理器
        
        Args:
            signer_client: lighter签名客户端
            redis_messenger: Redis消息管理器
            account_index: 账户索引
            retry_times: 对冲失败重试次数
        """
        self.signer_client = signer_client
        self.redis_messenger = redis_messenger
        self.account_index = account_index
        self.retry_times = retry_times
        self.running = False
        
        logging.info(f"B账户管理器初始化完成: account={account_index}")
    
    def on_a_account_filled(self, message: Dict[str, Any]):
        """
        收到A账户成交消息的回调
        
        Args:
            message: Redis消息
        """
        logging.info(f"收到A账户成交通知: {message}")
        
        # 在新的协程中执行对冲
        asyncio.create_task(self._execute_hedge(message))
    
    async def _execute_hedge(self, a_order_info: Dict[str, Any]):
        """
        执行对冲操作
        
        Args:
            a_order_info: A账户订单信息
        """
        try:
            market_index = a_order_info["market_index"]
            filled_base_amount = a_order_info["filled_base_amount"]
            
            logging.info(f"开始执行对冲: market={market_index}, amount={filled_base_amount}")
            
            # 重试机制
            for attempt in range(1, self.retry_times + 1):
                try:
                    success, order = await self._create_market_sell_order(
                        market_index,
                        filled_base_amount
                    )
                    
                    if success:
                        logging.info(f"对冲成功 (尝试 {attempt}/{self.retry_times})")
                        
                        # 发送B账户成交通知
                        await self._notify_hedge_completed(order, market_index)
                        return
                    else:
                        logging.warning(f"对冲失败 (尝试 {attempt}/{self.retry_times})")
                        if attempt < self.retry_times:
                            await asyncio.sleep(1)  # 重试前等待1秒
                
                except Exception as e:
                    logging.error(f"对冲异常 (尝试 {attempt}/{self.retry_times}): {e}")
                    if attempt < self.retry_times:
                        await asyncio.sleep(1)
            
            # 所有重试都失败
            logging.error("对冲失败，已达到最大重试次数！请人工介入！")
            raise Exception("对冲失败")
        
        except Exception as e:
            logging.error(f"执行对冲失败: {e}")
            raise
    
    async def _create_market_sell_order(self, market_index: int, base_amount: str) -> tuple:
        """
        创建市价卖单
        
        Args:
            market_index: 市场索引
            base_amount: 基础资产数量（字符串）
        
        Returns:
            (是否成功, 订单对象或None)
        """
        try:
            # 转换数量为整数
            amount_int = int(float(base_amount))
            
            # 生成client_order_index（使用时间戳+随机数避免冲突）
            import random
            client_order_index = int(time.time() * 1000) + random.randint(1, 999)
            
            # 创建市价卖单（无价格限制）
            logging.info(f"创建市价卖单: amount={amount_int}")
            
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                tx, resp, err = await self.signer_client.create_order(
                    market_index=market_index,
                    client_order_index=client_order_index,
                    base_amount=amount_int,
                    price=0,  # 市价单价格为0
                    is_ask=True,  # 卖单（做空）
                    order_type=lighter.SignerClient.ORDER_TYPE_MARKET,
                    time_in_force=lighter.SignerClient.ORDER_TIME_IN_FORCE_IMMEDIATE_OR_CANCEL,
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
                        logging.error(f"创建市价卖单失败: {err}")
                        return False, None
                
                if resp.code != 200:
                    logging.error(f"创建市价卖单失败: code={resp.code}, msg={resp.message}")
                    return False, None
                
                # 成功创建订单，跳出重试循环
                break
            else:
                # 重试次数用完
                logging.error(f"创建市价卖单失败，已重试{max_retries}次")
                return False, None
            
            logging.info(f"市价卖单创建成功: order_index={tx.order_index}")
            
            # 等待订单成交（市价单通常立即成交）
            await asyncio.sleep(2)
            
            # 查询订单状态确认成交
            order = await self._get_order_info(tx.order_index, market_index)
            
            if order and order.status == "filled":
                logging.info(f"市价卖单已成交: filled_amount={order.filled_base_amount}")
                return True, order
            else:
                logging.warning(f"市价卖单未完全成交或状态异常: status={order.status if order else 'unknown'}")
                return False, order
        
        except Exception as e:
            logging.error(f"创建市价卖单异常: {e}")
            return False, None
    
    async def _get_order_info(self, order_index: int, market_index: int):
        """
        获取订单信息
        
        Args:
            order_index: 订单索引
            market_index: 市场索引
        
        Returns:
            订单对象或None
        """
        try:
            order_api = lighter.OrderApi(self.signer_client.api_client)
            
            # 先查询非活跃订单（市价单成交后会在这里）
            inactive_orders = await order_api.account_inactive_orders(
                account_index=self.account_index,
                market_id=market_index,
                limit=10
            )
            
            if inactive_orders.orders:
                for order in inactive_orders.orders:
                    if order.order_index == order_index:
                        return order
            
            # 如果没找到，再查询活跃订单
            # 生成认证token
            auth_token, auth_error = self.signer_client.create_auth_token_with_expiry()
            if auth_error:
                logging.error(f"生成认证token失败: {auth_error}")
                return None
            
            active_orders = await order_api.account_active_orders(
                account_index=self.account_index,
                market_id=market_index,
                auth=auth_token
            )
            
            if active_orders.orders:
                for order in active_orders.orders:
                    if order.order_index == order_index:
                        return order
            
            return None
        
        except Exception as e:
            logging.error(f"获取订单信息失败: {e}")
            return None
    
    async def _notify_hedge_completed(self, order, market_index: int):
        """
        通知对冲完成
        
        Args:
            order: 订单对象
            market_index: 市场索引
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
                market_index=market_index,
                order_index=order.order_index,
                filled_base_amount=order.filled_base_amount,
                filled_quote_amount=order.filled_quote_amount,
                avg_price=avg_price,
                side="sell"
            )
            
            # 发布到Redis
            self.redis_messenger.publish_b_filled(message)
            logging.info("已发送B账户成交通知到Redis")
        
        except Exception as e:
            logging.error(f"发送对冲完成通知失败: {e}")
            raise
    
    def start_listening(self):
        """开始监听A账户成交消息"""
        self.running = True
        logging.info("B账户开始监听A账户成交消息")
    
    def stop_listening(self):
        """停止监听"""
        self.running = False
        logging.info("B账户停止监听")

