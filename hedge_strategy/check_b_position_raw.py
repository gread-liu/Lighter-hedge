#!/usr/bin/env python3
"""
查询B账户持仓信息 - 打印原始API返回数据
"""

import asyncio
import logging
import sys
import os
import json

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'temp_lighter'))

import lighter
from hedge_strategy.utils import load_config

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s:%(name)s:%(message)s'
)


async def main():
    """主函数"""
    # 加载配置
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    config = load_config(config_path)
    
    # B账户配置
    account_b_config = config['accounts']['account_b']
    account_index = account_b_config['account_index']
    
    print("=" * 80)
    print("查询B账户持仓信息 - 原始API返回数据")
    print("=" * 80)
    print(f"账户索引: {account_index}")
    print()
    
    # 创建SignerClient
    signer_client = lighter.SignerClient(
        url=config['lighter']['base_url'],
        private_key=account_b_config['api_key_private_key'],
        account_index=account_index,
        api_key_index=account_b_config['api_key_index']
    )
    
    # 创建AccountApi实例
    account_api = lighter.AccountApi(signer_client.api_client)
    
    # 查询账户信息
    print("-" * 80)
    print("调用 account_api.account() 接口...")
    print("-" * 80)
    
    account_data = await account_api.account(by="index", value=str(account_index))
    
    # 打印原始返回数据
    print()
    print("=" * 80)
    print("API原始返回数据（JSON格式）:")
    print("=" * 80)
    
    # 将对象转换为字典以便打印
    if account_data:
        # 打印完整的account_data对象
        print(f"\naccount_data类型: {type(account_data)}")
        print(f"account_data属性: {dir(account_data)}")
        
        if hasattr(account_data, 'to_dict'):
            data_dict = account_data.to_dict()
            print("\n完整的API返回数据:")
            print(json.dumps(data_dict, indent=2, ensure_ascii=False))
        else:
            print(f"\naccount_data: {account_data}")
        
        # 打印accounts列表
        if hasattr(account_data, 'accounts') and account_data.accounts:
            print("\n" + "=" * 80)
            print("账户列表 (accounts):")
            print("=" * 80)
            for i, account in enumerate(account_data.accounts):
                print(f"\n账户 #{i}:")
                if hasattr(account, 'to_dict'):
                    print(json.dumps(account.to_dict(), indent=2, ensure_ascii=False))
                else:
                    print(account)
                
                # 打印持仓信息
                if hasattr(account, 'positions') and account.positions:
                    print("\n" + "-" * 80)
                    print("持仓列表 (positions):")
                    print("-" * 80)
                    for j, position in enumerate(account.positions):
                        print(f"\n持仓 #{j}:")
                        if hasattr(position, 'to_dict'):
                            pos_dict = position.to_dict()
                            print(json.dumps(pos_dict, indent=2, ensure_ascii=False))
                            
                            # 解析持仓信息
                            market_id = pos_dict.get('market_id', 'N/A')
                            position_size = pos_dict.get('position', '0')
                            
                            market_name = "BTC" if market_id == 1 else ("ETH" if market_id == 0 else "未知")
                            
                            print(f"\n  市场: {market_name} (market_id={market_id})")
                            print(f"  持仓大小: {position_size}")
                            
                            try:
                                pos_float = float(position_size)
                                if pos_float > 0:
                                    print(f"  持仓方向: 空头 (正数=空头)")
                                elif pos_float < 0:
                                    print(f"  持仓方向: 多头 (负数=多头)")
                                else:
                                    print(f"  持仓方向: 无持仓")
                            except:
                                pass
                        else:
                            print(position)
    else:
        print("未获取到账户数据")
    
    print("\n" + "=" * 80)


if __name__ == "__main__":
    asyncio.run(main())