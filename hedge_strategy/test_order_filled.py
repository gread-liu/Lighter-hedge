"""
测试订单成交流程
模拟A账户订单成交，发送Redis消息给B账户
"""
import asyncio
import sys
from redis_messenger import RedisMessenger

async def test_order_filled():
    """测试订单成交通知"""
    print("=" * 60)
    print("测试A账户订单成交通知")
    print("=" * 60)
    
    # 初始化Redis
    redis_messenger = RedisMessenger(
        host='localhost',
        port=6388,
        db=0
    )
    redis_messenger.connect()
    
    # 模拟A账户成交消息
    test_message = {
        "account_index": 280459,
        "market_index": 1,
        "order_index": 999999999999,  # 测试订单号
        "filled_base_amount": "0.00020",
        "filled_quote_amount": "21.89",
        "avg_price": "109450.0",
        "timestamp": 1761216600,
        "side": "buy"
    }
    
    print(f"\n发送测试消息到Redis:")
    print(f"  账户: {test_message['account_index']}")
    print(f"  市场: {test_message['market_index']}")
    print(f"  订单号: {test_message['order_index']}")
    print(f"  成交数量: {test_message['filled_base_amount']}")
    print(f"  平均价格: {test_message['avg_price']}")
    print(f"  方向: {test_message['side']}")
    
    # 发布消息
    redis_messenger.publish_a_filled(test_message)
    
    print("\n✅ 测试消息已发送！")
    print("请查看B入口日志，应该会收到消息并执行对冲")
    
    # 关闭连接
    redis_messenger.close()

if __name__ == "__main__":
    asyncio.run(test_order_filled())