#!/usr/bin/env python3
"""
测试程序：查询Lighter账户总权益
探索AccountApi中可用的账户信息接口
"""

import asyncio
import logging
import sys
import os
from decimal import Decimal

# 添加temp_lighter到路径
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))

import lighter
from utils import load_config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)


async def test_account_equity():
    """测试查询账户权益信息"""
    
    print("=" * 80)
    print("测试Lighter账户权益查询接口")
    print("=" * 80)
    print()
    
    # 加载配置
    config = load_config('hedge_strategy/config.yaml')
    
    # 获取A账户配置
    account_a_config = config['accounts']['account_a']
    account_index = account_a_config['account_index']
    
    print(f"测试账户: {account_index}")
    print()
    
    # 创建API客户端
    api_client = lighter.ApiClient()
    
    try:
        # 创建AccountApi实例
        account_api = lighter.AccountApi(api_client)
        
        print("-" * 80)
        print("1. 测试 account() 方法 - 获取账户基本信息")
        print("-" * 80)
        
        # 通过索引查询账户
        account_data = await account_api.account(by="index", value=str(account_index))
        
        if account_data and account_data.accounts:
            account = account_data.accounts[0]
            
            print(f"\n账户索引: {account.account_index}")
            
            # 打印所有可用的属性
            print("\n账户对象的所有属性:")
            for attr in dir(account):
                if not attr.startswith('_'):
                    try:
                        value = getattr(account, attr)
                        if not callable(value):
                            print(f"  {attr}: {value}")
                    except:
                        pass
            
            # 检查是否有权益相关字段
            print("\n" + "=" * 80)
            print("查找权益相关字段:")
            print("=" * 80)
            
            equity_fields = ['equity', 'total_equity', 'account_equity', 'balance', 
                           'total_balance', 'margin', 'available_balance', 'wallet_balance',
                           'unrealized_pnl', 'realized_pnl']
            
            for field in equity_fields:
                if hasattr(account, field):
                    value = getattr(account, field)
                    print(f"✓ 找到字段 '{field}': {value}")
            
            # 打印持仓信息
            if hasattr(account, 'positions') and account.positions:
                print("\n" + "=" * 80)
                print("持仓信息:")
                print("=" * 80)
                for pos in account.positions:
                    print(f"\n市场ID: {pos.market_id}")
                    print(f"  持仓大小: {pos.position}")
                    print(f"  持仓方向: {pos.sign} (1=多头, -1=空头)")
                    
                    # 打印持仓对象的所有属性
                    print("  持仓对象的所有属性:")
                    for attr in dir(pos):
                        if not attr.startswith('_'):
                            try:
                                value = getattr(pos, attr)
                                if not callable(value):
                                    print(f"    {attr}: {value}")
                            except:
                                pass
        
        print("\n" + "=" * 80)
        print("2. 探索AccountApi的其他方法")
        print("=" * 80)
        
        # 列出AccountApi的所有方法
        print("\nAccountApi可用的方法:")
        for method in dir(account_api):
            if not method.startswith('_') and callable(getattr(account_api, method)):
                print(f"  - {method}")
        
        # 尝试其他可能的方法
        print("\n" + "=" * 80)
        print("3. 尝试其他可能的账户查询方法")
        print("=" * 80)
        
        # 检查是否有account_balance, account_info等方法
        potential_methods = ['account_balance', 'account_info', 'account_equity', 
                           'account_summary', 'get_account', 'get_balance']
        
        for method_name in potential_methods:
            if hasattr(account_api, method_name):
                print(f"\n✓ 找到方法: {method_name}")
                try:
                    method = getattr(account_api, method_name)
                    # 尝试调用（可能需要参数）
                    result = await method(account_index)
                    print(f"  结果: {result}")
                except Exception as e:
                    print(f"  调用失败: {e}")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # 关闭客户端
        await api_client.close()
    
    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)


async def test_b_account_equity():
    """测试查询B账户权益信息"""
    
    print("\n\n")
    print("=" * 80)
    print("测试B账户权益查询")
    print("=" * 80)
    print()
    
    # 加载配置
    config = load_config('hedge_strategy/config.yaml')
    
    # 获取B账户配置
    account_b_config = config['accounts']['account_b']
    account_index = account_b_config['account_index']
    
    print(f"测试账户: {account_index}")
    print()
    
    # 创建API客户端
    api_client = lighter.ApiClient()
    
    try:
        account_api = lighter.AccountApi(api_client)
        account_data = await account_api.account(by="index", value=str(account_index))
        
        if account_data and account_data.accounts:
            account = account_data.accounts[0]
            
            print(f"账户索引: {account.account_index}")
            
            # 查找权益相关字段
            equity_fields = ['equity', 'total_equity', 'account_equity', 'balance', 
                           'total_balance', 'margin', 'available_balance', 'wallet_balance']
            
            print("\n权益相关字段:")
            for field in equity_fields:
                if hasattr(account, field):
                    value = getattr(account, field)
                    print(f"  {field}: {value}")
    
    except Exception as e:
        print(f"\n❌ 错误: {e}")
    
    finally:
        await api_client.close()


if __name__ == "__main__":
    # 运行测试
    asyncio.run(test_account_equity())
    asyncio.run(test_b_account_equity())