#!/usr/bin/env python3
"""
查询A和B账户的持仓信息
"""

import sys
import os
import asyncio
import yaml
from pathlib import Path

# 添加temp_lighter到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))

from lighter import ApiClient, Configuration
from utils import get_positions

async def check_account_positions(config, account_key, account_name):
    """查询单个账户的持仓"""
    print(f"\n{'='*80}")
    print(f"{account_name}账户持仓信息")
    print(f"{'='*80}")
    
    account_config = config['accounts'][account_key]
    account_index = account_config['account_index']
    
    print(f"账户索引: {account_index}")
    
    # 初始化API客户端
    api_client = ApiClient(configuration=Configuration(host=config['lighter']['base_url']))
    
    # 查询BTC市场持仓
    print(f"\n{'-'*80}")
    print(f"BTC市场 (market_index=1) 持仓:")
    print(f"{'-'*80}\n")
    
    btc_position_size, btc_sign = await get_positions(api_client, account_index, 1)
    print(f"持仓大小: {btc_position_size:.5f}")
    print(f"持仓sign: {btc_sign}")
    print(f"持仓方向: {'多头' if btc_sign == 1 else '空头' if btc_sign == -1 else '无持仓'}")
    
    # 查询ETH市场持仓
    print(f"\n{'-'*80}")
    print(f"ETH市场 (market_index=0) 持仓:")
    print(f"{'-'*80}\n")
    
    eth_position_size, eth_sign = await get_positions(api_client, account_index, 0)
    print(f"持仓大小: {eth_position_size:.4f}")
    print(f"持仓sign: {eth_sign}")
    print(f"持仓方向: {'多头' if eth_sign == 1 else '空头' if eth_sign == -1 else '无持仓'}")
    
    return btc_position_size, eth_position_size

async def main():
    """主函数"""
    # 加载配置
    config_file = Path(__file__).parent / "config.yaml"
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    print("="*80)
    print("查询所有账户持仓")
    print("="*80)
    
    # 查询A账户
    a_btc, a_eth = await check_account_positions(config, 'account_a', 'A')
    
    # 查询B账户
    b_btc, b_eth = await check_account_positions(config, 'account_b', 'B')
    
    # 汇总
    print(f"\n{'='*80}")
    print("持仓汇总")
    print(f"{'='*80}")
    print(f"A账户 - BTC: {a_btc:.5f}, ETH: {a_eth:.4f}")
    print(f"B账户 - BTC: {b_btc:.5f}, ETH: {b_eth:.4f}")
    print(f"{'='*80}")

if __name__ == "__main__":
    asyncio.run(main())