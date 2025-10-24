import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))
import lighter
from lighter import ApiClient, Configuration
import yaml
from decimal import Decimal

async def check_position():
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    
    api_client = ApiClient(configuration=Configuration(host=config['lighter']['base_url']))
    account_api = lighter.AccountApi(api_client)
    
    # 查询B账户
    account_data = await account_api.account(by='index', value='280458')
    
    if account_data and account_data.accounts:
        print('B账户持仓详细信息：')
        for position in account_data.accounts[0].positions:
            if position.market_id == 1:  # BTC市场
                print(f'  市场ID: {position.market_id}')
                print(f'  持仓字符串: "{position.position}"')
                print(f'  持仓类型: {type(position.position)}')
                
                # 转换为Decimal
                pos_decimal = Decimal(position.position)
                print(f'  Decimal值: {pos_decimal}')
                print(f'  Decimal > 0: {pos_decimal > 0}')
                print(f'  Decimal < 0: {pos_decimal < 0}')
                
                # 转换为float
                pos_float = float(position.position)
                print(f'  Float值: {pos_float}')
                print(f'  Float > 0: {pos_float > 0}')
                print(f'  Float < 0: {pos_float < 0}')
                
                if pos_decimal > 0:
                    print(f'  ✅ 判断结果: 多头持仓，需要卖出平仓（is_ask=True）')
                elif pos_decimal < 0:
                    print(f'  ✅ 判断结果: 空头持仓，需要买入平仓（is_ask=False）')
                else:
                    print(f'  ✅ 判断结果: 无持仓')

asyncio.run(check_position())