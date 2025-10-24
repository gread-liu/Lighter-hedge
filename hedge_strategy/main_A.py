"""
跨账户对冲策略主程序 A
A账户挂限价单，完全成交后通过Redis通知B账户市价对冲
"""
import json
import sys
import os
import asyncio
import argparse
import logging
import signal
import time
from decimal import Decimal

from lighter import ApiClient, Configuration

# 添加temp_lighter到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))

import lighter
from redis_messenger import RedisMessenger
from account_a_manager import AccountAManager
from account_b_manager import AccountBManager
from utils import (
    load_config,
    get_market_index_by_name,
    cancel_all_orders, get_account_active_orders, get_positions
)


class HedgeStrategy:
    """跨账户对冲策略"""

    def __init__(self, config_path: str, market_name: str, quantity: int, depth: int):
        """
        初始化策略
        
        Args:
            config_path: 配置文件路径
            market_name: 市场名称（如 ETH, BTC, ENA）
            quantity: 挂单数量
            depth: 挂单档位
        """
        self.config_path = config_path
        self.market_name = market_name
        self.quantity = quantity
        self.depth = depth

        self.config = None
        self.market_index = None

        self.redis_messenger = None
        self.client_a = None
        self.api_client_a = None
        self.client_b = None
        self.api_client_b = None
        self.account_a_manager = None
        self.account_b_manager = None
        self.base_amount_multiplier = None
        self.price_multiplier = None

        self.running = False

        # 设置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        logging.info("=" * 60)
        logging.info("跨账户对冲策略启动")
        logging.info(f"市场: {market_name}, 数量: {quantity}, 档位: {depth}")
        logging.info("=" * 60)

    async def initialize(self):
        """初始化所有组件"""
        try:
            # 1. 加载配置文件
            logging.info("加载配置文件...")
            self.config = load_config(self.config_path)

            # 2. 初始化Redis
            logging.info("初始化Redis连接...")
            redis_config = self.config['redis']
            account_a_name = self.config['accounts']['account_a'].get('account_name', 'account_a')
            account_b_name = self.config['accounts']['account_b'].get('account_name', 'account_b')
            self.redis_messenger = RedisMessenger(
                host=redis_config['host'],
                port=redis_config['port'],
                db=redis_config['db'],
                account_a_name=account_a_name,
                account_b_name=account_b_name
            )
            self.redis_messenger.connect()

            # 3. 初始化A账户客户端
            logging.info("初始化A账户...")
            account_a_config = self.config['accounts']['account_a']
            self.client_a = lighter.SignerClient(
                url=self.config['lighter']['base_url'],
                private_key=account_a_config['api_key_private_key'],
                account_index=account_a_config['account_index'],
                api_key_index=account_a_config['api_key_index']
            )
            self.api_client_a = ApiClient(configuration=Configuration(host=self.config['lighter']['base_url']))

            # 4. 查询市场索引
            logging.info(f"查询市场索引: {self.market_name}...")
            orderBook = await get_market_index_by_name(
                self.client_a.api_client,
                self.market_name
            )
            self.market_index = orderBook.market_id
            self.base_amount_multiplier = pow(10, orderBook.supported_size_decimals)
            self.price_multiplier = pow(10, orderBook.supported_price_decimals)

            if self.market_index is None:
                raise Exception(f"未找到市场: {self.market_name}")

            # 5. 取消历史挂单
            logging.info("清理历史挂单...")
            await cancel_all_orders(
                self.client_a,
                account_a_config['account_index'],
                self.market_index
            )

            # 6. 初始化A账户管理器
            logging.info("初始化A账户管理器...")
            self.account_a_manager = AccountAManager(
                signer_client=self.client_a,
                redis_messenger=self.redis_messenger,
                account_index=account_a_config['account_index'],
                market_index=self.market_index,
                base_amount=self.quantity,
                depth=self.depth,
                poll_interval=self.config['strategy']['poll_interval'],
                ws_url=self.config['lighter'].get('ws_url')
            )

            # 7. 启动WebSocket监听A账户订单成交
            logging.info("启动WebSocket监听A账户订单成交...")
            self.account_a_manager.start_ws_monitoring()
            
            # 等待WebSocket连接建立
            await asyncio.sleep(2)

            logging.info("初始化完成！")

        except Exception as e:
            logging.error(f"初始化失败: {e}")
            raise

    async def run(self):
        """运行策略主循环"""
        self.running = True

        cycle_count = 0

        try:
            while self.running:
                cycle_count += 1
                logging.info("")
                logging.info("=" * 60)
                logging.info(f"开始第 {cycle_count} 轮循环")
                logging.info("=" * 60)

                # 检查是否需要暂停交易
                if self.account_a_manager.pause_trading:
                    logging.error("⚠️ 交易已暂停（B账户对冲失败），等待人工处理...")
                    await asyncio.sleep(10)
                    continue

                # 第一步 查询出活跃订单
                logging.info("第一步 查询出活跃订单")
                active_orders = await get_account_active_orders(
                    self.client_a,
                    self.config['accounts']['account_a']['account_index'],
                    self.market_index
                )
                # print(active_orders)
                json_str = json.dumps(active_orders, default=obj_to_dict, ensure_ascii=False)
                print(json_str)

                # 第二步 查询持仓情况（如果活跃单超过1分钟不成交，则取消活跃单）
                logging.info("第二步 查询持仓情况")
                position_size, sign, available_balance = await get_positions(
                    self.api_client_a,
                    self.config['accounts']['account_a']['account_index'],
                    self.market_index
                )
                logging.info(f"持仓情况: size={position_size}, sign={sign}")
                
                # 同步持仓到Redis
                account_a_name = self.config['accounts']['account_a'].get('account_name', 'account_a')
                account_a_index = self.config['accounts']['account_a']['account_index']
                self.redis_messenger.update_position(
                    account_name=account_a_name,
                    account_index=account_a_index,
                    market=self.market_name,
                    position_size=position_size,
                    sign=sign,
                    available_balance=available_balance
                )
                
                # 验证对冲状态：检查A和B账户持仓是否正确对冲
                hedge_valid, hedge_message = self._check_hedge_status()
                if not hedge_valid:
                    logging.warning(f"⚠️ 对冲状态异常: {hedge_message}")
                    # 如果持仓超过配置的超时时间未对冲，执行全部平仓
                    force_close_timeout = self.config['strategy'].get('force_close_timeout', 30)
                    if f"超过{force_close_timeout}秒" in hedge_message:
                        logging.error(f"❌ 持仓超过{force_close_timeout}秒未对冲，执行全部平仓！")
                        await self._emergency_close_all_positions()
                        await asyncio.sleep(10)
                        continue
                    # 如果对冲不匹配但未超时，等待下一轮检查
                    await asyncio.sleep(5)
                    continue

                # 第三步 核心逻辑处理
                # |- 如果持仓不存在，活跃单不存在，则限价开多
                # |- 如果持仓存在，活跃单不存在，则限价平多
                # |- 如果持仓不存在，活跃单存在，则不做任何处理
                # |- 如果持仓存在，活跃单存在，则不做任何处理

                if position_size == 0 and not active_orders:
                    """
                        如果持仓不存在，活跃单不存在，则限价开多
                    """
                    # 步骤1: A账户创建限价买单
                    logging.info("[第三步] 如果持仓不存在，活跃单不存在，则限价开多...")
                    success = await self.account_a_manager.create_limit_buy_order(
                        self.base_amount_multiplier,
                        self.price_multiplier,
                        active_orders  # 传递已查询的活跃订单
                    )
                    if not success:
                        logging.warning("创建订单失败，5秒后重试...")
                        await asyncio.sleep(5)
                        continue
                    
                elif position_size > 0 and sign == 1 and not active_orders:
                    """
                       如果持仓存在且是多头，活跃单不存在，则限价平多
                    """
                    logging.info("[第三步] 如果持仓存在且是多头，活跃单不存在，则限价平多...")
                    success = await self.account_a_manager.create_limit_sell_order(
                        self.base_amount_multiplier,
                        self.price_multiplier,
                        active_orders  # 传递已查询的活跃订单
                    )
                    if not success:
                        logging.warning("创建订单失败，5秒后重试...")
                        await asyncio.sleep(5)
                        continue
                    
                elif position_size > 0 and sign == -1:
                    """
                       如果持仓是空头，这是异常情况，记录错误
                    """
                    logging.error(f"⚠️ 异常：A账户出现空头持仓！size={position_size}, sign={sign}")
                    logging.error("A账户只应该有多头持仓，请人工检查并清空持仓！")
                    await asyncio.sleep(10)
                    continue
                else:
                    """
                        情况1：如果持仓不存在，活跃单存在，则不做任何处理
                        情况2：如果持仓存在，活跃单存在，则不做任何处理
                        补偿逻辑：如果活跃单超过1分钟，则取消该订单
                    """
                    for active_order in active_orders:
                        created_at = active_order.additional_properties["created_at"]
                        if int(time.time()) - created_at > self.config['lighter']['maker_order_time_out']:
                            # 取消订单
                            try:
                                await self.client_a.cancel_order(
                                    market_index=self.market_index,
                                    order_index=active_order.order_index
                                )
                                logging.info(f"已取消订单: {active_order.order_index}")
                            except Exception as e:
                                logging.error(f"取消订单{active_order.order_index}失败: {e}")
                        else:
                            logging.info("不做任何处理，没有超时活跃单")


                await asyncio.sleep(5)  # 短暂休息

        except Exception as e:
            logging.error(f"策略运行异常: {e}")
            raise

        finally:
            await self.cleanup()

    async def cleanup(self):
        """清理资源"""
        logging.info("清理资源...")

        try:
            # 停止监控
            if self.account_a_manager:
                self.account_a_manager.stop_monitoring()
                self.account_a_manager.stop_ws_monitoring()

            if self.account_b_manager:
                self.account_b_manager.stop_listening()

            # 取消所有挂单
            if self.client_a and self.market_index:
                logging.info("取消A账户挂单...")
                await cancel_all_orders(
                    self.client_a,
                    self.config['accounts']['account_a']['account_index'],
                    self.market_index
                )

            if self.client_b and self.market_index:
                logging.info("取消B账户挂单...")
                await cancel_all_orders(
                    self.client_b,
                    self.config['accounts']['account_b']['account_index'],
                    self.market_index
                )

            # 关闭Redis连接
            if self.redis_messenger:
                self.redis_messenger.close()

            # 关闭API客户端
            if self.client_a:
                await self.client_a.close()

            if self.client_b:
                await self.client_b.close()

            logging.info("清理完成")

        except Exception as e:
            logging.error(f"清理资源失败: {e}")

    def _check_hedge_status(self) -> tuple[bool, str]:
        """
        检查A和B账户的对冲状态
        
        Returns:
            (是否对冲正常, 状态消息)
        """
        try:
            import time
            
            # 从Redis获取A和B账户持仓
            account_a_name = self.config['accounts']['account_a'].get('account_name', 'account_a')
            account_b_name = self.config['accounts']['account_b'].get('account_name', 'account_b')
            pos_a = self.redis_messenger.get_position_by_account_name(account_a_name, self.market_name)
            pos_b = self.redis_messenger.get_position_by_account_name(account_b_name, self.market_name)
            
            if not pos_a or not pos_b:
                return True, "持仓信息未同步到Redis，跳过检查"
            
            size_a = pos_a.get("size", 0)
            sign_a = pos_a.get("sign", 0)
            timestamp_a = pos_a.get("timestamp", 0)
            
            size_b = pos_b.get("size", 0)
            sign_b = pos_b.get("sign", 0)
            timestamp_b = pos_b.get("timestamp", 0)
            
            # 如果两个账户都没有持仓，认为对冲正常
            if size_a == 0 and size_b == 0:
                return True, "两个账户都无持仓"
            
            # 获取强制平仓超时配置
            force_close_timeout = self.config['strategy'].get('force_close_timeout', 30)
            
            # 检查持仓大小是否相等
            if abs(size_a - size_b) > 0.00001:  # 允许微小误差
                # 检查持仓时间，如果超过配置的超时时间，需要平仓
                current_time = time.time()
                max_timestamp = max(timestamp_a, timestamp_b)
                if current_time - max_timestamp > force_close_timeout:
                    return False, f"持仓大小不匹配且超过{force_close_timeout}秒: A={size_a}, B={size_b}"
                return False, f"持仓大小不匹配: A={size_a}, B={size_b}"
            
            # 检查持仓方向是否相反
            if sign_a != 0 and sign_b != 0 and sign_a == sign_b:
                # 检查持仓时间
                current_time = time.time()
                max_timestamp = max(timestamp_a, timestamp_b)
                if current_time - max_timestamp > force_close_timeout:
                    return False, f"持仓方向相同且超过{force_close_timeout}秒: A={sign_a}, B={sign_b}"
                return False, f"持仓方向相同（应该相反）: A={sign_a}, B={sign_b}"
            
            # 对冲正常
            return True, f"对冲正常: A={size_a}({sign_a}), B={size_b}({sign_b})"
            
        except Exception as e:
            logging.error(f"检查对冲状态异常: {e}")
            return True, f"检查异常，跳过: {e}"
    
    async def _emergency_close_all_positions(self):
        """
        紧急平仓：智能决定平仓策略
        
        策略：
        1. 只有A有仓位: 取消A的活动单 + 平A的仓位
        2. A和B都有仓位: 取消A的活动单 + 平A的仓位 + 平B的仓位
        """
        try:
            logging.error("=" * 60)
            logging.error("执行紧急平仓操作")
            logging.error("=" * 60)
            
            # 获取A和B账户持仓
            account_a_name = self.config['accounts']['account_a'].get('account_name', 'account_a')
            account_b_name = self.config['accounts']['account_b'].get('account_name', 'account_b')
            pos_a = self.redis_messenger.get_position_by_account_name(account_a_name, self.market_name)
            pos_b = self.redis_messenger.get_position_by_account_name(account_b_name, self.market_name)
            
            if not pos_a or not pos_b:
                logging.error("无法获取持仓信息，请手动执行清仓脚本")
                logging.error("⚠️ 请手动执行: python3 hedge_strategy/quick_clear_all.py")
                return
            
            size_a = abs(pos_a.get("size", 0))
            size_b = abs(pos_b.get("size", 0))
            
            logging.info(f"A账户持仓: {size_a}, B账户持仓: {size_b}")
            
            # 第一步：取消A账户所有活跃订单
            logging.info("取消A账户所有活跃订单...")
            await cancel_all_orders(
                self.client_a,
                self.config['accounts']['account_a']['account_index'],
                self.market_index
            )
            logging.info("A账户活跃订单已取消")
            
            # 第二步：判断平仓策略
            if size_a > 0 and size_b == 0:
                # 情况1: 只有A有仓位，直接平A
                logging.info(f"只有A账户有仓位({size_a})，平A账户")
                await self._close_account_a_position()
            elif size_a > 0 and size_b > 0:
                # 情况2: A和B都有仓位，两边都平
                logging.info(f"A和B都有仓位(A={size_a}, B={size_b})，两边都平")
                await self._close_account_a_position()
                await self._send_close_signal_to_b()
            elif size_a == 0 and size_b > 0:
                # 情况3: 只有B有仓位，只平B
                logging.info(f"只有B账户有仓位({size_b})，平B账户")
                await self._send_close_signal_to_b()
            
            logging.error("=" * 60)
            
        except Exception as e:
            logging.error(f"紧急平仓失败: {e}")
    
    async def _close_account_a_position(self):
        """平掉A账户持仓"""
        try:
            from utils import get_positions, get_orderbook
            from decimal import Decimal
            import random
            
            position_size, sign, _ = await get_positions(
                self.api_client_a,
                self.config['accounts']['account_a']['account_index'],
                self.market_index
            )
            
            if position_size == 0:
                logging.info("A账户无持仓，无需平仓")
                return
            
            logging.info(f"开始平A账户持仓: size={position_size}, sign={sign}")
            
            # 获取当前市场价格
            orderbook = await get_orderbook(self.api_client_a, self.market_index)
            
            # 根据持仓方向确定平仓方向和价格
            # 参考B账户的逻辑,使用5%滑点容忍度确保市价单成交
            slippage_tolerance = Decimal('0.05')
            
            if sign == 1:
                # 平多头，需要卖出，使用买一价并下调5%
                is_ask = True
                price_dec = Decimal(str(orderbook.bids[0].price))
                base_price = int(price_dec * self.price_multiplier)
                avg_execution_price = int(base_price * (Decimal('1') - slippage_tolerance))
                logging.info(f"平多头: 卖出, 基准价={price_dec}, 执行价={avg_execution_price}")
            else:
                # 平空头，需要买入，使用卖一价并上浮5%
                is_ask = False
                price_dec = Decimal(str(orderbook.asks[0].price))
                base_price = int(price_dec * self.price_multiplier)
                avg_execution_price = int(base_price * (Decimal('1') + slippage_tolerance))
                logging.info(f"平空头: 买入, 基准价={price_dec}, 执行价={avg_execution_price}")
            
            # 生成client_order_index
            client_order_index = int(time.time() * 1000) + random.randint(1, 999)
            
            # 使用create_market_order方法下市价单
            tx, resp, err = await self.client_a.create_market_order(
                market_index=self.market_index,
                client_order_index=client_order_index,
                base_amount=int(position_size * self.base_amount_multiplier),
                avg_execution_price=avg_execution_price,
                is_ask=is_ask,
                reduce_only=True  # 平仓单
            )
            
            if err:
                logging.error(f"A账户平仓订单失败: {err}")
                return
            
            if resp and resp.code == 200:
                logging.info(f"✅ A账户平仓订单已提交: tx_hash={resp.tx_hash}")
            else:
                logging.error(f"A账户平仓订单失败: code={resp.code if resp else 'None'}")
            
        except Exception as e:
            logging.error(f"平A账户持仓失败: {e}")
    
    async def _send_close_signal_to_b(self):
        """通过Redis发送平仓信号给B账户"""
        try:
            logging.info("发送平仓信号给B账户...")
            
            # 发布平仓信号到Redis
            close_message = {
                "action": "close_all",
                "market": self.market_name,
                "market_index": self.market_index,
                "timestamp": int(time.time())
            }
            
            self.redis_messenger.publish_a_filled(close_message)
            logging.info(f"已发送平仓信号: {close_message}")
            
        except Exception as e:
            logging.error(f"发送平仓信号失败: {e}")
    
    def stop(self):
        """停止策略"""
        logging.info("收到停止信号...")
        self.running = False


# 方式1：使用 default 参数
def obj_to_dict(obj):
    return obj.__dict__


async def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='跨账户对冲策略')
    parser.add_argument('--market', type=str, required=True, help='市场名称（如 ETH, BTC, ENA）')
    parser.add_argument('--quantity', type=Decimal, required=True, help='挂单数量（base_amount）')
    parser.add_argument('--depth', type=int, required=True, help='挂单档位（1表示买1/卖1）')
    parser.add_argument('--config', type=str,
                        default='/Users/liujian/Documents/workspances/Lighter-hedge/hedge_strategy/config.yaml',
                        help='配置文件路径')

    args = parser.parse_args()

    # 创建策略实例
    strategy = HedgeStrategy(
        config_path=args.config,
        market_name=args.market,
        quantity=args.quantity,
        depth=args.depth
    )

    # 设置信号处理
    def signal_handler(signum, frame):
        logging.info(f"收到信号 {signum}")
        strategy.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        # 初始化
        await strategy.initialize()

        # 运行策略
        await strategy.run()

    except KeyboardInterrupt:
        logging.info("用户中断")
    except Exception as e:
        logging.error(f"程序异常退出: {e}")
        raise
    finally:
        logging.info("程序退出")


if __name__ == "__main__":
    asyncio.run(main())
