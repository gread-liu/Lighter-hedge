"""
B账户管理器
负责市价卖单对冲
"""

import sys
import os
import asyncio
import logging
import time
import threading
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
        base_amount_multiplier: int,
        price_multiplier: int,
        retry_times: int = 3
    ):
        """
        初始化B账户管理器
        
        Args:
            signer_client: lighter签名客户端
            redis_messenger: Redis消息管理器
            account_index: 账户索引
            base_amount_multiplier: 基础资产数量乘数（精度）
            price_multiplier: 价格乘数（精度）
            retry_times: 对冲失败重试次数
        """
        self.signer_client = signer_client
        self.redis_messenger = redis_messenger
        self.account_index = account_index
        self.base_amount_multiplier = base_amount_multiplier
        self.price_multiplier = price_multiplier
        self.retry_times = retry_times
        self.running = False
        self.event_loop = None
        
        logging.info(f"B账户管理器初始化完成: account={account_index}, base_multiplier={base_amount_multiplier}, price_multiplier={price_multiplier}")
    
    def set_event_loop(self, loop):
        """设置事件循环"""
        self.event_loop = loop
    
    def on_a_account_filled(self, message: Dict[str, Any]):
        """
        收到A账户成交消息的回调
        
        Args:
            message: Redis消息
        """
        logging.info(f"收到A账户成交通知: {message}")
        
        # 检查是否是平仓信号
        if message.get("action") == "close_all":
            logging.warning("⚠️ 收到紧急平仓信号！")
            # 使用线程安全的方式调度平仓任务
            if self.event_loop and self.event_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self._execute_close_all(message),
                    self.event_loop
                )
            else:
                logging.error("事件循环未设置或未运行，无法执行平仓")
            return
        
        # 正常的对冲逻辑
        # 使用线程安全的方式调度异步任务
        if self.event_loop and self.event_loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._execute_hedge(message),
                self.event_loop
            )
        else:
            logging.error("事件循环未设置或未运行，无法执行对冲")
    
    async def _execute_close_all(self, message: Dict[str, Any]):
        """
        执行全部平仓操作
        
        Args:
            message: 平仓消息
        """
        try:
            logging.error("=" * 60)
            logging.error("B账户开始执行紧急平仓")
            logging.error("=" * 60)
            
            market = message.get("market", "")
            market_index = message.get("market_index", 0)
            logging.info(f"平仓市场: {market}, market_index: {market_index}")
            
            # 获取当前持仓
            from utils import get_positions
            position_size, sign = await get_positions(
                self.signer_client.api_client,
                self.account_index,
                market_index
            )
            
            if position_size == 0:
                logging.info("B账户无持仓，无需平仓")
                return
            
            logging.info(f"B账户当前持仓: size={position_size}, sign={sign}")
            
            # 获取当前市场价格
            from utils import get_orderbook
            from decimal import Decimal
            orderbook = await get_orderbook(self.signer_client.api_client, market_index)
            
            # 根据持仓方向确定平仓方向和价格
            # sign=1表示多头,需要卖出平仓(is_ask=True)
            # sign=-1表示空头,需要买入平仓(is_ask=False)
            if sign == 1:
                # 平多头，卖出
                is_ask = True
                price_dec = Decimal(str(orderbook.bids[0].price))
                base_price = int(price_dec * self.price_multiplier)
                # 降低5%确保成交
                avg_execution_price = int(base_price * Decimal('0.95'))
                action = "卖出"
            else:
                # 平空头，买入
                is_ask = False
                price_dec = Decimal(str(orderbook.asks[0].price))
                base_price = int(price_dec * self.price_multiplier)
                # 提高5%确保成交
                avg_execution_price = int(base_price * Decimal('1.05'))
                action = "买入"
            
            logging.info(f"B账户平仓: {action}, 基准价={base_price}, 执行价={avg_execution_price}")
            
            # 生成client_order_index
            import random
            client_order_index = int(time.time() * 1000) + random.randint(1, 999)
            
            # 下市价单
            tx, resp, err = await self.signer_client.create_market_order(
                market_index=market_index,
                client_order_index=client_order_index,
                base_amount=int(position_size * self.base_amount_multiplier),
                avg_execution_price=avg_execution_price,
                is_ask=is_ask,
                reduce_only=True  # 平仓单
            )
            
            if err:
                logging.error(f"B账户平仓订单创建失败: {err}")
                return
            
            if resp and resp.code == 200:
                logging.info(f"B账户平仓订单已提交: tx_hash={resp.tx_hash}")
            else:
                logging.error(f"B账户平仓订单提交失败: code={resp.code if resp else 'None'}")
            
            logging.error("=" * 60)
            
        except Exception as e:
            logging.error(f"B账户执行平仓失败: {e}")
    
    async def _execute_hedge(self, a_order_info: Dict[str, Any]):
        """
        执行对冲操作
        
        Args:
            a_order_info: A账户订单信息
        """
        try:
            market_index = a_order_info["market_index"]
            filled_base_amount = a_order_info["filled_base_amount"]
            avg_price = a_order_info["avg_price"]
            a_side = a_order_info.get("side", "buy")  # A账户的订单方向
            
            logging.info(f"开始执行对冲: market={market_index}, amount={filled_base_amount}, avg_price={avg_price}, A方向={a_side}")
            
            # 重试机制
            for attempt in range(1, self.retry_times + 1):
                try:
                    success, order = await self._create_hedge_order(
                        market_index,
                        filled_base_amount,
                        avg_price,
                        a_side
                    )
                    
                    if success:
                        logging.info(f"对冲成功 (尝试 {attempt}/{self.retry_times})")
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
            logging.error("❌ 对冲失败，已达到最大重试次数！")
            raise Exception("对冲失败")
        
        except Exception as e:
            logging.error(f"执行对冲失败: {e}")
            raise
    
    async def _create_hedge_order(self, market_index: int, base_amount: str, avg_price: str, a_side: str) -> tuple:
        """
        创建对冲订单（市价单）
        
        对冲逻辑：B账户始终做与A账户相反的方向
        - A买入（buy）→ B卖出（sell, is_ask=True）
        - A卖出（sell）→ B买入（buy, is_ask=False）
        
        这样无论A是开仓还是平仓，B都能正确对冲
        
        Args:
            market_index: 市场索引
            base_amount: 基础资产数量（字符串，如"0.00020"）
            avg_price: A账户平均成交价格（字符串，如"109400.0"）
            a_side: A账户订单方向（"buy"或"sell"）
        
        Returns:
            (是否成功, 订单对象或None)
        """
        try:
            # 转换数量为整数，使用与A入口相同的方式
            amount_float = float(base_amount)
            amount_int = int(amount_float * self.base_amount_multiplier)
            
            # 转换价格为整数格式，并增加滑点容忍度
            # 市价单需要更宽松的价格范围以避免被取消
            from decimal import Decimal
            price_dec = Decimal(avg_price)
            base_price = int(price_dec * self.price_multiplier)
            
            # 根据方向增加滑点容忍度（5%）
            # 买入时价格上浮5%，卖出时价格下调5%
            slippage_tolerance = 0.05
            if a_side == "sell":  # B需要买入
                # 买入时，愿意接受更高的价格
                avg_execution_price = int(base_price * (1 + slippage_tolerance))
            else:  # a_side == "buy"，B需要卖出
                # 卖出时，愿意接受更低的价格
                avg_execution_price = int(base_price * (1 - slippage_tolerance))
            
            # 确定B账户的订单方向（对冲方向）
            # B账户始终做与A账户相反的方向
            # A买入（buy）→ B卖出（sell, is_ask=True）
            # A卖出（sell）→ B买入（buy, is_ask=False）
            if a_side == "buy":
                is_ask = True  # B卖出
                b_action = "卖出"
            else:  # a_side == "sell"
                is_ask = False  # B买入
                b_action = "买入"
            
            logging.info(f"数量转换: {base_amount} * {self.base_amount_multiplier} = {amount_int}")
            logging.info(f"价格转换: {avg_price} * {self.price_multiplier} = {avg_execution_price}")
            logging.info(f"对冲逻辑: A账户{'买入' if a_side == 'buy' else '卖出'} → B账户{b_action} (is_ask={is_ask})")
            
            # 生成client_order_index（使用时间戳+随机数避免冲突）
            import random
            client_order_index = int(time.time() * 1000) + random.randint(1, 999)
            
            # 使用lighter SDK的create_market_order方法
            logging.info(f"创建市价{b_action}单: amount={amount_int}, avg_execution_price={avg_execution_price}")
            
            max_retries = 3
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    logging.info(f"准备创建市价订单: market={market_index}, amount={amount_int}, avg_price={avg_execution_price}, client_order_index={client_order_index}")
                    
                    # 使用create_market_order方法
                    tx, resp, err = await self.signer_client.create_market_order(
                        market_index=market_index,
                        client_order_index=client_order_index,
                        base_amount=amount_int,
                        avg_execution_price=avg_execution_price,
                        is_ask=is_ask,  # 根据A的方向决定B的方向
                        reduce_only=False
                    )
                    
                    logging.info(f"创建订单返回: tx={tx}, resp={resp}, err={err}")
                except Exception as create_err:
                    logging.error(f"调用create_market_order异常: {create_err}", exc_info=True)
                    return False, None
                
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
                        logging.error(f"创建市价{b_action}单失败: {err}")
                        return False, None
                
                if resp is None:
                    logging.error(f"创建市价{b_action}单失败: resp为None")
                    return False, None
                    
                if resp.code != 200:
                    logging.error(f"创建市价{b_action}单失败: code={resp.code}, msg={resp.message}")
                    return False, None
                
                # 成功创建订单，跳出重试循环
                break
            else:
                # 重试次数用完
                logging.error(f"创建市价{b_action}单失败，已重试{max_retries}次")
                return False, None
            
            # 从tx_hash中提取order_index，或者使用client_order_index查询
            logging.info(f"市价{b_action}单创建成功: tx_hash={resp.tx_hash}, client_order_index={client_order_index}")
            
            # 等待订单上链并成交（市价单通常立即成交，但需要更长时间上链）
            # 使用重试机制查询订单状态
            max_query_retries = 5  # 最多查询5次
            query_interval = 3  # 每次间隔3秒
            
            for query_attempt in range(1, max_query_retries + 1):
                logging.info(f"等待{query_interval}秒后查询订单状态 (尝试 {query_attempt}/{max_query_retries})...")
                await asyncio.sleep(query_interval)
                
                # 使用client_order_index查询订单状态确认成交
                logging.info(f"查询订单状态: client_order_index={client_order_index}")
                order = await self._get_order_info_by_client_index(client_order_index, market_index)
                
                if order:
                    if order.status == "filled":
                        logging.info(f"✅ 市价{b_action}单已成交: filled_amount={order.filled_base_amount}")
                        return True, order
                    elif order.status.startswith("canceled"):
                        logging.warning(f"❌ 市价{b_action}单被取消: status={order.status}")
                        return False, order
                    else:
                        logging.info(f"⏳ 订单状态: {order.status}, 继续等待...")
                        # 继续下一次查询
                else:
                    logging.warning(f"⚠️ 未找到订单 (尝试 {query_attempt}/{max_query_retries})")
                    # 继续下一次查询
            
            # 所有查询都失败
            logging.error(f"❌ 查询订单超时，已尝试{max_query_retries}次")
            return False, None
        
        except Exception as e:
            logging.error(f"创建市价对冲单异常: {e}")
            return False, None
    
    async def _get_order_info_by_client_index(self, client_order_index: int, market_index: int):
        """
        根据client_order_index获取订单信息
        
        Args:
            client_order_index: 客户端订单索引
            market_index: 市场索引
        
        Returns:
            订单对象或None
        """
        try:
            order_api = lighter.OrderApi(self.signer_client.api_client)
            
            # 生成认证token
            auth_token, auth_error = self.signer_client.create_auth_token_with_expiry()
            if auth_error:
                logging.error(f"生成认证token失败: {auth_error}")
                return None
            
            # 先查询非活跃订单（市价单成交后会在这里）
            inactive_orders = await order_api.account_inactive_orders(
                account_index=self.account_index,
                market_id=market_index,
                limit=10,
                auth=auth_token
            )
            
            if inactive_orders.orders:
                for order in inactive_orders.orders:
                    if order.client_order_index == client_order_index:
                        logging.info(f"在非活跃订单中找到订单: order_index={order.order_index}, status={order.status}")
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
                    if order.client_order_index == client_order_index:
                        logging.info(f"在活跃订单中找到订单: order_index={order.order_index}, status={order.status}")
                        return order
            
            logging.warning(f"未找到client_order_index={client_order_index}的订单")
            return None
        
        except Exception as e:
            logging.error(f"获取订单信息失败: {e}")
            return None
    
    async def _notify_hedge_completed(self, order, market_index: int):
        """
        通知对冲成功
        
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
            
            # 创建消息，side根据订单的is_ask判断
            side = "sell" if order.is_ask else "buy"
            
            message = RedisMessenger.create_filled_message(
                account_index=self.account_index,
                market_index=market_index,
                order_index=order.order_index,
                filled_base_amount=order.filled_base_amount,
                filled_quote_amount=order.filled_quote_amount,
                avg_price=avg_price,
                side=side
            )
            
            # 添加成功状态
            message["status"] = "success"
            
            # 发布到Redis
            self.redis_messenger.publish_b_filled(message)
            logging.info("✅ 已发送B账户对冲成功通知到Redis")
        
        except Exception as e:
            logging.error(f"发送对冲完成通知失败: {e}")
            raise
    
    async def _notify_hedge_result(self, market_index: int, a_order_info: Dict[str, Any],
                                   status: str, reason: str = None, order=None):
        """
        通知对冲结果（成功或失败）
        
        Args:
            market_index: 市场索引
            a_order_info: A账户订单信息
            status: 状态（"success"或"failed"）
            reason: 失败原因（仅失败时需要）
            order: 订单对象（仅成功时需要）
        """
        try:
            import time
            
            if status == "failed":
                # 失败消息
                message = {
                    "account_index": self.account_index,
                    "market_index": market_index,
                    "status": "failed",
                    "reason": reason,
                    "a_order_info": a_order_info,
                    "timestamp": int(time.time()),
                    "retry_times": self.retry_times
                }
                logging.error(f"❌ 发送B账户对冲失败通知: {message}")
            else:
                # 成功消息（不应该走这个分支，应该用_notify_hedge_completed）
                message = {
                    "account_index": self.account_index,
                    "market_index": market_index,
                    "status": "success",
                    "timestamp": int(time.time())
                }
                logging.info(f"✅ 发送B账户对冲成功通知: {message}")
            
            # 发布到Redis的CHANNEL_B_FILLED
            self.redis_messenger.publish_b_filled(message)
        
        except Exception as e:
            logging.error(f"发送对冲结果通知异常: {e}")
            raise
    
    def start_listening(self):
        """开始监听A账户成交消息"""
        self.running = True
        logging.info("B账户开始监听A账户成交消息")
    
    def stop_listening(self):
        """停止监听"""
        self.running = False
        logging.info("B账户停止监听")
