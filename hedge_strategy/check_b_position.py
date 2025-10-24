#!/usr/bin/env python3
"""
查询B账户持仓信息
"""

import sys
import os
import asyncio
import yaml
from pathlib import Path

# 添加temp_lighter到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))

import lighter
from lighter import ApiClient, Configuration

async def main():
    """主函数"""
    # 加载配置
    config_file = Path(__file__).parent / "config.yaml"
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    # 初始化B账户客户端
    account_b_config = config['accounts']['account_b']
    client = lighter.SignerClient(
        url=config['lighter']['base_url'],
        private_key=account_b_config['api_key_private_key'],
        account_index=account_b_config['account_index'],
        api_key_index=account_b_config['api_key_index']
    )
    
    api_client = ApiClient(configuration=Configuration(host=config['lighter']['base_url']))
    
    print("=" * 80)
    print("查询B账户持仓信息")
    print("=" * 80)
    print(f"账户索引: {account_b_config['account_index']}")
    print()
    
    # 查询BTC市场持仓
    print("-" * 80)
    print("BTC市场 (market_index=1) 持仓:")
    print("-" * 80)
    
    try:
        # 使用utils中的函数查询持仓
        from utils import get_positions
        
        position_size, sign = await get_positions(
            api_client,
            account_b_config['account_index'],
            1  # BTC市场
        )
        
        print(f"\n持仓大小: {position_size}")
        print(f"持仓sign: {sign}")
        print(f"持仓方向: {'多头' if sign == 1 else '空头' if sign == -1 else '无持仓'}")
        print(f"持仓说明: sign=1为多头，sign=-1为空头")
        
        # 查询ETH市场持仓
        print()
        print("-" * 80)
        print("ETH市场 (market_index=0) 持仓:")
        print("-" * 80)
        
        eth_position_size, eth_sign = await get_positions(
            api_client,
            account_b_config['account_index'],
            0  # ETH市场
        )
        
        print(f"\n持仓大小: {eth_position_size}")
        print(f"持仓sign: {eth_sign}")
        print(f"持仓方向: {'多头' if eth_sign == 1 else '空头' if eth_sign == -1 else '无持仓'}")
        print(f"持仓说明: sign=1为多头，sign=-1为空头")
            
    except Exception as e:
        print(f"查询失败: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    print("=" * 80)
    
    await client.close()

if __name__ == "__main__":
    asyncio.run(main())