#!/usr/bin/env python3
"""
一键清空所有账户的持仓和订单
使用市价单快速平仓
"""

import sys
import os
import asyncio
import yaml
import logging
from pathlib import Path

# 添加temp_lighter到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))

import lighter
from lighter import ApiClient, Configuration

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(message)s'
)

async def cancel_all_orders(client, api_client, account_index, market_index, account_name):
    """取消所有活跃订单"""
    try:
        from utils import get_account_active_orders
        orders = await get_account_active_orders(client, account_index, market_index)
        
        if not orders or len(orders) == 0:
            logging.info(f"✅ {account_name}账户没有活跃订单")
            return True
        
        logging.info(f"📋 {account_name}账户有 {len(orders)} 个活跃订单，开始取消...")
        
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
                    await asyncio.sleep(0.5)  # 避免请求过快
                    
            except Exception as e:
                logging.error(f"❌ 取消订单异常: {order_index}, {e}")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ 查询订单失败: {e}")
        return False

async def close_position_market(client, api_client, account_index, market_index, account_name):
    """使用市价单平仓"""
    try:
        from utils import get_positions
        
        # 查询持仓
        position_size, sign = await get_positions(api_client, account_index, market_index)
        
        if position_size == 0:
            logging.info(f"✅ {account_name}账户没有持仓")
            return True
        
        # 判断平仓方向
        if sign == 1:
            # 多头持仓，需要卖出平仓
            is_ask = True
            side_name = "多头"
            action = "卖出平仓"
        elif sign == -1:
            # 空头持仓，需要买入平仓
            is_ask = False
            side_name = "空头"
            action = "买入平仓"
        else:
            logging.error(f"❌ 未知的sign值: {sign}")
            return False
        
        logging.info(f"📊 {account_name}持仓: {position_size}, 方向: {side_name}, 操作: {action}")
        
        # 获取市场信息
        from utils import get_market_index_by_name
        markets = ["BTC", "ETH", "ENA"]
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
        
        # 转换数量
        abs_position_size = abs(position_size)
        base_amount = int(abs_position_size * base_multiplier)
        
        # 获取当前市场价格作为参考
        from utils import get_orderbook_price_at_depth
        if is_ask:
            # 卖出时参考买5价
            price_str = await get_orderbook_price_at_depth(api_client, market_index, 5, is_bid=True)
        else:
            # 买入时参考卖5价
            price_str = await get_orderbook_price_at_depth(api_client, market_index, 5, is_bid=False)
        
        ref_price = float(price_str) if price_str else 0
        if ref_price == 0:
            logging.error("❌ 无法获取市场价格")
            return False
        
        # 增加5%滑点容忍度，确保市价单能成交
        slippage_tolerance = 0.05
        if is_ask:
            # 卖出时，愿意接受更低的价格
            avg_execution_price = int(ref_price * price_multiplier * (1 - slippage_tolerance))
        else:
            # 买入时，愿意接受更高的价格
            avg_execution_price = int(ref_price * price_multiplier * (1 + slippage_tolerance))
        
        logging.info(f"🔄 创建市价{'卖' if is_ask else '买'}单: amount={base_amount}, ref_price={ref_price}")
        
        # 创建市价单
        tx, resp, err = await client.create_market_order(
            market_index=market_index,
            client_order_index=0,
            base_amount=base_amount,
            avg_execution_price=avg_execution_price,
            is_ask=is_ask,
            reduce_only=False
        )
        
        if err:
            logging.error(f"❌ 创建市价单失败: {err}")
            return False
        
        logging.info(f"✅ 市价单创建成功: tx_hash={resp.tx_hash}")
        
        # 等待订单上链
        await asyncio.sleep(5)
        
        # 验证持仓是否已平
        await asyncio.sleep(3)
        new_position_size, new_sign = await get_positions(api_client, account_index, market_index)
        
        if new_position_size == 0:
            logging.info(f"✅ 市价单已成交，持仓已清空")
            return True
        else:
            logging.warning(f"⚠️ 持仓可能未完全平掉，剩余: {new_position_size}")
            return False
        
    except Exception as e:
        logging.error(f"❌ 平仓失败: {e}")
        import traceback
        traceback.print_exc()
        return False

async def clear_account(config, account_key, account_name):
    """清空单个账户"""
    logging.info(f"\n{'='*80}")
    logging.info(f"开始清空 {account_name} 账户")
    logging.info(f"{'='*80}")
    
    account_config = config['accounts'][account_key]
    
    # 初始化客户端
    client = lighter.SignerClient(
        url=config['lighter']['base_url'],
        private_key=account_config['api_key_private_key'],
        account_index=account_config['account_index'],
        api_key_index=account_config['api_key_index']
    )
    
    api_client = ApiClient(configuration=Configuration(host=config['lighter']['base_url']))
    
    # 处理BTC市场
    logging.info(f"\n--- BTC市场 (market_index=1) ---")
    await cancel_all_orders(client, api_client, account_config['account_index'], 1, account_name)
    await close_position_market(client, api_client, account_config['account_index'], 1, account_name)
    
    # 处理ETH市场
    logging.info(f"\n--- ETH市场 (market_index=0) ---")
    await cancel_all_orders(client, api_client, account_config['account_index'], 0, account_name)
    await close_position_market(client, api_client, account_config['account_index'], 0, account_name)
    
    await client.close()
    
    logging.info(f"\n✅ {account_name} 账户清空完成")

async def main():
    """主函数"""
    # 加载配置
    config_file = Path(__file__).parent / "config.yaml"
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    logging.info("="*80)
    logging.info("一键清空所有账户")
    logging.info("="*80)
    
    # 清空A账户
    await clear_account(config, 'account_a', 'A')
    
    # 清空B账户
    await clear_account(config, 'account_b', 'B')
    
    logging.info("\n"+"="*80)
    logging.info("✅ 所有账户清空完成！")
    logging.info("="*80)

if __name__ == "__main__":
    asyncio.run(main())