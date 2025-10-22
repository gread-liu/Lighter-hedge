"""
跨账户对冲策略主程序 A
A账户挂限价单，完全成交后通过Redis通知B账户市价对冲
"""

import sys
import os
import asyncio
import argparse
import logging
import signal
from decimal import Decimal

# 添加temp_lighter到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))

import lighter
from redis_messenger import RedisMessenger
from account_a_manager import AccountAManager
from account_b_manager import AccountBManager
from utils import (
    load_config,
    get_market_index_by_name,
    cancel_all_orders
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
        self.client_b = None
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
                poll_interval=self.config['strategy']['poll_interval']
            )

            # 7. 设置Redis订阅
            logging.info("设置Redis订阅...")
            self.redis_messenger.subscribe(
                RedisMessenger.CHANNEL_B_FILLED,
                self.account_b_manager.on_a_account_filled
            )
            self.redis_messenger.start_listening()

            # todo 8. WS监听A账户的通知


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

                # 步骤1: A账户创建限价买单
                logging.info("[步骤1] A账户创建限价买单...")
                success = await self.account_a_manager.create_limit_buy_order(self.base_amount_multiplier,
                                                                              self.price_multiplier)

                if not success:
                    logging.warning("创建订单失败，5秒后重试...")
                    await asyncio.sleep(5)
                    continue

                # 步骤2: 监控订单直到完全成交
                logging.info("[步骤2] 监控A账户订单状态...")
                await self.account_a_manager.monitor_order_until_filled()

                # 步骤3: 等待B账户对冲完成
                logging.info("[步骤3] 等待B账户对冲完成...")
                await self.account_a_manager.wait_for_b_filled(timeout=300)

                # 步骤4: 准备下一轮
                logging.info(f"第 {cycle_count} 轮完成，准备下一轮...")
                await asyncio.sleep(2)  # 短暂休息

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
