"""
测试对冲逻辑
测试A账户开多和平多两种情况下B账户的对冲行为
"""
import asyncio
import sys
from redis_messenger import RedisMessenger

async def test_hedge_logic():
    """测试对冲逻辑"""
    print("=" * 60)
    print("测试对冲逻辑")
    print("=" * 60)
    
    # 初始化Redis
    redis_messenger = RedisMessenger(
        host='localhost',
        port=6388,
        db=0
    )
    redis_messenger.connect()
    
    # 测试1: A账户开多（buy）→ B账户应该开空（sell）
    print("\n【测试1】A账户开多 → B账户开空")
    print("-" * 60)
    test_message_buy = {
        "account_index": 280459,
        "market_index": 1,
        "order_index": 888888888888,
        "filled_base_amount": "0.00020",
        "filled_quote_amount": "21.89",
        "avg_price": "109450.0",
        "timestamp": 1761216600,
        "side": "buy"  # A开多
    }
    
    print(f"发送消息: A账户{test_message_buy['side']} (开多)")
    print(f"  预期: B账户应该开空（sell, is_ask=True）")
    redis_messenger.publish_a_filled(test_message_buy)
    print("✅ 消息已发送，请查看B入口日志")
    
    # 等待5秒
    print("\n等待5秒...")
    await asyncio.sleep(5)
    
    # 测试2: A账户平多（sell）→ B账户应该平空（buy）
    print("\n【测试2】A账户平多 → B账户平空")
    print("-" * 60)
    test_message_sell = {
        "account_index": 280459,
        "market_index": 1,
        "order_index": 999999999999,
        "filled_base_amount": "0.00020",
        "filled_quote_amount": "21.91",
        "avg_price": "109550.0",
        "timestamp": 1761216605,
        "side": "sell"  # A平多
    }
    
    print(f"发送消息: A账户{test_message_sell['side']} (平多)")
    print(f"  预期: B账户应该平空（buy, is_ask=False）")
    redis_messenger.publish_a_filled(test_message_sell)
    print("✅ 消息已发送，请查看B入口日志")
    
    print("\n" + "=" * 60)
    print("测试完成！请查看B入口日志验证对冲方向是否正确")
    print("=" * 60)
    
    # 关闭连接
    redis_messenger.close()

if __name__ == "__main__":
    asyncio.run(test_hedge_logic())