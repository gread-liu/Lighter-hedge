"""
跨账户对冲策略主程序 B
B账户订阅Redis消息，收到A账户成交通知后执行市价对冲
"""

import sys
import os
import asyncio
import argparse
import logging
import signal
from decimal import Decimal

from lighter import ApiClient, Configuration

# 添加temp_lighter到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))

import lighter
from redis_messenger import RedisMessenger
from account_b_manager import AccountBManager
from utils import (
    load_config,
    get_market_index_by_name,
    cancel_all_orders
)


class HedgeStrategyB:
    """跨账户对冲策略 - B入口（订阅和对冲）"""

    def __init__(self, config_path: str, market_name: str):
        """
        初始化策略
        
        Args:
            config_path: 配置文件路径
            market_name: 市场名称（如 ETH, BTC, ENA）
        """
        self.config_path = config_path
        self.market_name = market_name

        self.config = None
        self.market_index = None

        self.redis_messenger = None
        self.client_b = None
        self.api_client_b = None
        self.account_b_manager = None
        self.base_amount_multiplier = None
        self.price_multiplier = None

        self.running = False
        self._position_sync_running = False  # 持仓同步线程标志位
        self.position_sync_thread = None  # 持仓同步线程

        # 设置日志
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s [%(levelname)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )

        logging.info("=" * 60)
        logging.info("跨账户对冲策略B启动 - 订阅模式")
        logging.info(f"市场: {market_name}")
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

            # 3. 初始化B账户客户端
            logging.info("初始化B账户...")
            account_b_config = self.config['accounts']['account_b']
            self.client_b = lighter.SignerClient(
                url=self.config['lighter']['base_url'],
                private_key=account_b_config['api_key_private_key'],
                account_index=account_b_config['account_index'],
                api_key_index=account_b_config['api_key_index']
            )
            self.api_client_b = ApiClient(configuration=Configuration(host=self.config['lighter']['base_url']))

            # 4. 查询市场索引
            logging.info(f"查询市场索引: {self.market_name}...")
            orderBook = await get_market_index_by_name(
                self.client_b.api_client,
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
                self.client_b,
                account_b_config['account_index'],
                self.market_index
            )

            # 6. 初始化B账户管理器
            logging.info("初始化B账户管理器...")
            self.account_b_manager = AccountBManager(
                signer_client=self.client_b,
                redis_messenger=self.redis_messenger,
                account_index=account_b_config['account_index'],
                base_amount_multiplier=self.base_amount_multiplier,
                price_multiplier=self.price_multiplier,
                retry_times=self.config['strategy']['retry_times']
            )
            
            # 设置事件循环
            self.account_b_manager.set_event_loop(asyncio.get_event_loop())

            # 7. 设置Redis订阅 - B入口只订阅A账户的成交消息
            logging.info("设置Redis订阅...")
            # 使用实例的channel,而不是类变量
            self.redis_messenger.subscribe(
                self.redis_messenger.CHANNEL_A_FILLED,
                self.account_b_manager.on_a_account_filled
            )
            self.redis_messenger.start_listening()

            # 8. 启动持仓同步定时任务
            logging.info("启动B账户持仓同步定时任务...")
            self._start_position_sync()
            
            logging.info("初始化完成！B账户开始监听A账户成交消息...")

        except Exception as e:
            logging.error(f"初始化失败: {e}")
            raise

    async def run(self):
        """运行策略主循环 - B入口只需要保持监听状态"""
        self.running = True
        self.account_b_manager.start_listening()

        try:
            logging.info("B账户进入监听模式，等待A账户成交通知...")
            
            # B入口的主循环只需要保持运行状态，实际的对冲逻辑由Redis回调触发
            while self.running:
                # 定期检查连接状态
                await asyncio.sleep(10)
                
                # 可以在这里添加健康检查逻辑
                if not self.redis_messenger._running:
                    logging.warning("Redis连接断开，尝试重新连接...")
                    try:
                        self.redis_messenger.start_listening()
                    except Exception as e:
                        logging.error(f"重新连接Redis失败: {e}")

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
            if self.account_b_manager:
                self.account_b_manager.stop_listening()

            # 取消所有挂单
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
            if self.client_b:
                await self.client_b.close()

            logging.info("清理完成")

        except Exception as e:
            logging.error(f"清理资源失败: {e}")

    def stop(self):
        """停止策略"""
        logging.info("收到停止信号...")
        self.running = False
        self._position_sync_running = False  # 停止持仓同步线程
    
    def _start_position_sync(self):
        """启动B账户持仓同步定时任务"""
        import threading
        import time
        from utils import get_positions
        
        # 设置标志位,让持仓同步线程可以运行
        self._position_sync_running = True
        
        # 保存主事件循环的引用
        main_loop = asyncio.get_event_loop()
        
        def sync_positions():
            """定时同步B账户持仓到Redis"""
            # 持仓同步线程使用独立的标志位
            while self._position_sync_running:
                try:
                    # 使用asyncio.run_coroutine_threadsafe将协程提交到主事件循环
                    future = asyncio.run_coroutine_threadsafe(
                        get_positions(
                            self.api_client_b,
                            self.config['accounts']['account_b']['account_index'],
                            self.market_index
                        ),
                        main_loop
                    )
                    
                    # 等待结果(最多10秒超时)
                    position_size, sign, available_balance = future.result(timeout=10)
                    
                    # 更新到Redis
                    account_b_name = self.config['accounts']['account_b'].get('account_name', 'account_b')
                    account_b_index = self.config['accounts']['account_b']['account_index']
                    
                    logging.info(f"同步B账户持仓: size={position_size}, sign={sign}")
                    self.redis_messenger.update_position(
                        account_name=account_b_name,
                        account_index=account_b_index,
                        market=self.market_name,
                        position_size=position_size,
                        sign=sign,
                        available_balance=available_balance
                    )
                    
                except Exception as e:
                    logging.error(f"同步B账户持仓失败: {e}")
                
                # 等待5秒
                time.sleep(5)
        
        self.position_sync_thread = threading.Thread(target=sync_positions, daemon=True)
        self.position_sync_thread.start()
        logging.info("B账户持仓同步线程已启动（每5秒同步一次）")


async def main():
    """主函数"""
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='跨账户对冲策略 - B入口（订阅模式）')
    parser.add_argument('--market', type=str, required=True, help='市场名称（如 ETH, BTC, ENA）')
    parser.add_argument('--config', type=str,
                        default='/Users/liujian/Documents/workspances/Lighter-hedge/hedge_strategy/config.yaml',
                        help='配置文件路径')

    args = parser.parse_args()

    # 创建策略实例
    strategy = HedgeStrategyB(
        config_path=args.config,
        market_name=args.market
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
