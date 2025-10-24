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
            self.redis_messenger = RedisMessenger(
                host=redis_config['host'],
                port=redis_config['port'],
                db=redis_config['db']
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
                get_position = await get_positions(
                    self.api_client_a,
                    self.config['accounts']['account_a']['account_index'],
                    self.market_index
                )
                print(get_position)

                # 第三步 核心逻辑处理
                # |- 如果持仓不存在，活跃单不存在，则限价开多
                # |- 如果持仓存在，活跃单不存在，则限价平多
                # |- 如果持仓不存在，活跃单存在，则不做任何处理
                # |- 如果持仓存在，活跃单存在，则不做任何处理

                if get_position == 0 and not active_orders:
                    """
                        如果持仓不存在，活跃单不存在，则限价开多
                    """
                    # 步骤1: A账户创建限价买单
                    logging.info("[第三步] 如果持仓不存在，活跃单不存在，则限价开多...")
                    success = await self.account_a_manager.create_limit_buy_order(self.base_amount_multiplier,
                                                                                  self.price_multiplier)
                    if not success:
                        logging.warning("创建订单失败，5秒后重试...")
                        await asyncio.sleep(5)
                        continue
                elif get_position != 0 and not active_orders:
                    """
                       如果持仓存在，活跃单不存在，则限价平多
                    """
                    logging.info("[第三步] 如果持仓存在，活跃单不存在，则限价平多...")
                    success = await self.account_a_manager.create_limit_sell_order(self.base_amount_multiplier,
                                                                                   self.price_multiplier)
                    if not success:
                        logging.warning("创建订单失败，5秒后重试...")
                        await asyncio.sleep(5)
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

                # # 步骤2: 监控订单直到完全成交
                # logging.info("[步骤2] 监控A账户订单状态...")
                # await self.account_a_manager.monitor_order_until_filled()
                #
                # # 步骤3: 等待B账户对冲完成
                # logging.info("[步骤3] 等待B账户对冲完成...")
                # await self.account_a_manager.wait_for_b_filled(timeout=300)
                #
                # # 步骤4: 准备下一轮
                # logging.info(f"第 {cycle_count} 轮完成，准备下一轮...")
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
