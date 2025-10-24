#!/usr/bin/env python3
"""
一键清空A、B两个账户的程序
功能：
1. 取消所有活跃订单
2. 平掉所有持仓
3. 支持单独清空或同时清空两个账户
"""

import sys
import os
import asyncio
import argparse
import logging
import yaml
from pathlib import Path

# 添加temp_lighter到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))

import lighter
from lighter import ApiClient, Configuration

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


class AccountCleaner:
    """账户清理器"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """初始化清理器"""
        self.config = self._load_config(config_path)
        self.clients = {}
        
    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        config_file = Path(__file__).parent / config_path
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    
    async def _init_client(self, account_name: str):
        """初始化客户端"""
        account_config = self.config['accounts'][account_name]
        
        client = lighter.SignerClient(
            url=self.config['lighter']['base_url'],
            private_key=account_config['api_key_private_key'],
            account_index=account_config['account_index'],
            api_key_index=account_config['api_key_index']
        )
        
        api_client = ApiClient(configuration=Configuration(host=self.config['lighter']['base_url']))
        
        logging.info(f"✅ {account_name}账户客户端初始化成功")
        return client, api_client
    
    async def cancel_all_orders(self, client, account_index: int,
                               market_index: int, account_name: str) -> int:
        """取消所有活跃订单"""
        logging.info(f"\n{'='*60}")
        logging.info(f"开始取消{account_name}账户的所有活跃订单...")
        logging.info(f"{'='*60}")
        
        # 使用utils中的函数查询活跃订单
        try:
            from utils import get_account_active_orders
            orders = await get_account_active_orders(
                client,
                account_index,
                market_index
            )
        except Exception as e:
            logging.error(f"❌ 查询活跃订单失败: {e}")
            return 0
        
        if not orders:
            logging.info(f"✅ {account_name}账户没有活跃订单")
            return 0
        
        logging.info(f"📋 找到 {len(orders)} 个活跃订单")
        
        # 取消所有订单
        cancelled_count = 0
        for order in orders:
            order_index = order.order_index
            try:
                tx, resp, err = await client.cancel_order(
                    market_index=market_index,
                    order_index=order_index
                )
                
                if err:
                    logging.error(f"❌ 取消订单失败: {order_index}, 错误: {err}")
                else:
                    logging.info(f"✅ 已取消订单: {order_index}")
                    cancelled_count += 1
                    
                # 避免请求过快
                await asyncio.sleep(0.5)
                
            except Exception as e:
                logging.error(f"❌ 取消订单异常: {order_index}, {str(e)}")
        
        logging.info(f"\n✅ {account_name}账户订单取消完成: {cancelled_count}/{len(orders)}")
        return cancelled_count
    
    async def close_all_positions(self, client, api_client, account_index: int,
                                  market_index: int, account_name: str) -> bool:
        """平掉所有持仓（使用市价单）"""
        logging.info(f"\n{'='*60}")
        logging.info(f"开始平掉{account_name}账户的所有持仓...")
        logging.info(f"{'='*60}")
        
        # 查询持仓
        try:
            from utils import get_positions
            position_size, sign = await get_positions(api_client, account_index, market_index)
        except Exception as e:
            logging.error(f"❌ 查询持仓失败: {e}")
            return False
        
        if position_size == 0:
            logging.info(f"✅ {account_name}账户没有持仓")
            return True
        
        logging.info(f"📊 当前持仓: {position_size}, sign={sign}")
        
        # 判断持仓方向和平仓方向
        # 根据API返回的sign字段判断：
        # sign = 1 → 多头持仓，需要卖出平仓（is_ask=True）
        # sign = -1 → 空头持仓，需要买入平仓（is_ask=False）
        abs_position_size = abs(position_size)
        
        if sign == 1:
            # sign=1 = 多头持仓，需要卖出平仓
            is_ask = True
            side_name = "多头"
            action = "卖出平仓"
        elif sign == -1:
            # sign=-1 = 空头持仓，需要买入平仓
            is_ask = False
            side_name = "空头"
            action = "买入平仓"
        else:
            logging.error(f"❌ 未知的sign值: {sign}")
            return False
        
        logging.info(f"📍 持仓类型: {side_name}, 需要{action} (is_ask={is_ask})")
        
        # 获取市场信息
        try:
            from utils import get_market_index_by_name
            # 获取市场符号
            markets = ["BTC", "ETH", "ENA"]  # 常见市场
            market_symbol = None
            for symbol in markets:
                orderbook = await get_market_index_by_name(api_client, symbol)
                if orderbook.market_id == market_index:
                    market_symbol = symbol
                    base_multiplier = pow(10, orderbook.supported_size_decimals)
                    price_multiplier = pow(10, orderbook.supported_price_decimals)
                    break
            
            if not market_symbol:
                logging.error("❌ 无法找到市场信息")
                return False
                
        except Exception as e:
            logging.error(f"❌ 获取市场信息失败: {e}")
            return False
        
        # 转换为整数（使用绝对值）
        base_amount = int(abs_position_size * base_multiplier)
        
        # 获取当前市场价格用于市价单
        try:
            from utils import get_orderbook_price_at_depth
            # 平仓时使用更激进的价格确保成交：
            # - 平空头（买入）：使用卖5档价格（更高的价格，确保能买到）
            # - 平多头（卖出）：使用买5档价格（更低的价格，确保能卖出）
            if is_ask:  # 卖出平仓（平多头）
                price_str = await get_orderbook_price_at_depth(api_client, market_index, 5, is_bid=True)
            else:  # 买入平仓（平空头）
                price_str = await get_orderbook_price_at_depth(api_client, market_index, 5, is_bid=False)
            
            avg_price = float(price_str) if price_str else 0
        except Exception as e:
            logging.error(f"❌ 获取市场价格失败: {e}")
            avg_price = 0
        
        if avg_price == 0:
            logging.error(f"❌ 无法获取市场价格")
            return False
        
        avg_execution_price = int(avg_price * price_multiplier)
        
        logging.info(f"💰 平仓价格: {avg_price}, 数量: {abs_position_size}")
        
        # 重试机制
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            try:
                logging.info(f"尝试创建市价平仓单 (第{attempt}次)")
                
                # 先取消所有订单，确保没有挂单
                from utils import cancel_all_orders
                await cancel_all_orders(client, account_index, market_index)
                await asyncio.sleep(0.5)
                
                # 重新查询持仓（可能在取消订单过程中有变化）
                from utils import get_positions
                current_position, current_sign = await get_positions(api_client, account_index, market_index)
                
                if current_position == 0:
                    logging.info(f"✅ {account_name}账户持仓已清空")
                    return True
                
                # 重新计算平仓参数
                abs_current_position = abs(current_position)
                # 根据sign判断：sign=1为多头，sign=-1为空头
                current_is_ask = current_sign == 1  # sign=1=多头，需要卖出；sign=-1=空头，需要买入
                current_base_amount = int(abs_current_position * base_multiplier)
                
                logging.info(f"当前持仓: {current_position}, sign={current_sign}, 持仓类型: {'多头' if current_sign == 1 else '空头'}, 平仓方向: {'卖出' if current_is_ask else '买入'}")
                
                # 使用create_market_order创建市价单
                tx, resp, err = await client.create_market_order(
                    market_index=market_index,
                    client_order_index=0,
                    base_amount=current_base_amount,
                    avg_execution_price=avg_execution_price,
                    is_ask=current_is_ask,
                    reduce_only=False
                )
                
                logging.info(f"创建订单返回: tx={tx}, resp={resp}, err={err}")
                
                if err:
                    # 检查是否是nonce错误
                    if "invalid nonce" in str(err).lower():
                        logging.warning(f"Nonce错误，刷新后重试 (尝试 {attempt}/{max_retries})")
                        client.nonce_manager.hard_refresh_nonce(client.api_key_index)
                        await asyncio.sleep(1)
                        continue
                    else:
                        logging.error(f"❌ 平仓失败: {err}")
                        if attempt < max_retries:
                            await asyncio.sleep(1)
                            continue
                        return False
                
                if resp is None:
                    logging.error(f"❌ 平仓失败: 响应为None")
                    if attempt < max_retries:
                        await asyncio.sleep(1)
                        continue
                    return False
                
                if resp.code != 200:
                    logging.error(f"❌ 平仓失败: code={resp.code}, msg={resp.message}")
                    if attempt < max_retries:
                        await asyncio.sleep(1)
                        continue
                    return False
                
                logging.info(f"✅ 市价平仓单创建成功")
                logging.info(f"📝 交易哈希: {resp.tx_hash if resp else 'N/A'}")
                
                # 等待订单执行（市价单通常立即成交）
                await asyncio.sleep(3)
                
                # 验证持仓是否已平
                new_position_size, new_sign = await get_positions(api_client, account_index, market_index)
                
                if new_position_size == 0:
                    logging.info(f"✅ {account_name}账户持仓已成功平掉")
                    return True
                else:
                    logging.warning(f"⚠️ 持仓可能未完全平掉，剩余: {new_position_size}")
                    if attempt < max_retries:
                        logging.info(f"准备重试...")
                        await asyncio.sleep(1)
                        continue
                    return False
                    
            except Exception as e:
                logging.error(f"❌ 平仓异常 (尝试 {attempt}/{max_retries}): {str(e)}")
                if attempt < max_retries:
                    await asyncio.sleep(1)
                    continue
                return False
        
        logging.error(f"❌ 平仓失败，已重试{max_retries}次")
        return False
    
    async def clear_account(self, account_name: str, market_symbol: str = "BTC") -> bool:
        """清空指定账户"""
        logging.info(f"\n{'#'*60}")
        logging.info(f"# 开始清空{account_name}账户")
        logging.info(f"{'#'*60}")
        
        try:
            # 初始化客户端
            if account_name not in self.clients:
                client, api_client = await self._init_client(account_name)
                self.clients[account_name] = (client, api_client)
            
            client, api_client = self.clients[account_name]
            account_config = self.config['accounts'][account_name]
            account_index = account_config['account_index']
            
            # 获取市场索引
            from utils import get_market_index_by_name
            orderbook = await get_market_index_by_name(api_client, market_symbol)
            market_index = orderbook.market_id
            
            if market_index is None:
                logging.error(f"❌ 未找到市场: {market_symbol}")
                return False
            
            logging.info(f"📍 市场: {market_symbol}, 索引: {market_index}")
            
            # 1. 取消所有订单
            cancelled = await self.cancel_all_orders(
                client, account_index, market_index, account_name
            )
            
            # 2. 平掉所有持仓
            closed = await self.close_all_positions(
                client, api_client, account_index, market_index, account_name
            )
            
            logging.info(f"\n{'='*60}")
            logging.info(f"✅ {account_name}账户清空完成！")
            logging.info(f"   - 取消订单: {cancelled} 个")
            logging.info(f"   - 平仓状态: {'成功' if closed else '失败或无持仓'}")
            logging.info(f"{'='*60}")
            
            return True
            
        except Exception as e:
            logging.error(f"❌ 清空{account_name}账户失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return False
    
    async def clear_all_accounts(self, market_symbol: str = "BTC"):
        """清空所有账户"""
        logging.info(f"\n{'#'*60}")
        logging.info(f"# 开始清空所有账户")
        logging.info(f"{'#'*60}\n")
        
        results = {}
        
        # 清空A账户
        results['account_a'] = await self.clear_account('account_a', market_symbol)
        
        # 等待一下
        await asyncio.sleep(1)
        
        # 清空B账户
        results['account_b'] = await self.clear_account('account_b', market_symbol)
        
        # 总结
        logging.info(f"\n{'#'*60}")
        logging.info(f"# 清空结果汇总")
        logging.info(f"{'#'*60}")
        logging.info(f"A账户: {'✅ 成功' if results['account_a'] else '❌ 失败'}")
        logging.info(f"B账户: {'✅ 成功' if results['account_b'] else '❌ 失败'}")
        logging.info(f"{'#'*60}\n")


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='一键清空A、B账户的订单和持仓')
    parser.add_argument(
        '--account',
        choices=['a', 'b', 'all'],
        default='all',
        help='要清空的账户: a=A账户, b=B账户, all=所有账户 (默认: all)'
    )
    parser.add_argument(
        '--market',
        default='BTC',
        help='市场符号 (默认: BTC)'
    )
    
    args = parser.parse_args()
    
    cleaner = AccountCleaner()
    
    if args.account == 'all':
        await cleaner.clear_all_accounts(args.market)
    elif args.account == 'a':
        await cleaner.clear_account('account_a', args.market)
    elif args.account == 'b':
        await cleaner.clear_account('account_b', args.market)


if __name__ == "__main__":
    asyncio.run(main())