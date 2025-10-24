import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))
import lighter
from lighter import ApiClient, Configuration
import yaml

async def check_position():
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    
    api_client = ApiClient(configuration=Configuration(host=config['lighter']['base_url']))
    account_api = lighter.AccountApi(api_client)
    
    # 查询B账户
    account_data = await account_api.account(by='index', value='280458')
    
    if account_data and account_data.accounts:
        print('B账户持仓信息：')
        for position in account_data.accounts[0].positions:
            if position.market_id == 1:  # BTC市场
                print(f'  市场ID: {position.market_id}')
                print(f'  持仓: {position.position}')
                print(f'  持仓数值: {float(position.position)}')
                if float(position.position) > 0:
                    print(f'  持仓类型: 多头（需要卖出平仓）')
                elif float(position.position) < 0:
                    print(f'  持仓类型: 空头（需要买入平仓）')
                else:
                    print(f'  持仓类型: 无持仓')

asyncio.run(check_position())