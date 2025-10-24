import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))
import lighter
from lighter import ApiClient, Configuration
import yaml

async def check_orders():
    with open('config.yaml', 'r') as f:
        config = yaml.safe_load(f)
    
    client = lighter.SignerClient(
        url=config['lighter']['base_url'],
        private_key=config['accounts']['account_b']['api_key_private_key'],
        account_index=config['accounts']['account_b']['account_index'],
        api_key_index=config['accounts']['account_b']['api_key_index']
    )
    
    auth_token, _ = client.create_auth_token_with_expiry()
    order_api = lighter.OrderApi(client.api_client)
    
    # 查询活跃订单
    orders = await order_api.account_active_orders(
        account_index=280458,
        market_id=1,
        auth=auth_token
    )
    
    print(f'B账户活跃订单数: {len(orders.orders) if orders.orders else 0}')
    if orders.orders:
        for order in orders.orders:
            print(f'  订单ID: {order.order_index}, 类型: {order.order_type}, 方向: {"卖" if order.is_ask else "买"}, 数量: {order.initial_base_amount}, 价格: {order.price}')

asyncio.run(check_orders())