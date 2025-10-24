"""
测试Redis消息传递
模拟A账户成交消息，验证B入口是否能正确响应
"""
import redis
import json
import time

# 连接Redis
r = redis.Redis(host='localhost', port=6388, db=0, decode_responses=True)

# 创建模拟的A账户成交消息
test_message = {
    "account_index": 280459,
    "market_index": 1,
    "order_index": 999999999,
    "filled_base_amount": "0.00020",
    "filled_quote_amount": "21.88",
    "avg_price": "109400.0",
    "timestamp": int(time.time()),
    "side": "buy"
}

print("发送测试消息到Redis...")
print(f"Channel: hedge:account_a_filled")
print(f"Message: {json.dumps(test_message, indent=2)}")

# 发布消息
result = r.publish('hedge:account_a_filled', json.dumps(test_message))
print(f"\n消息已发送，订阅者数量: {result}")

if result == 0:
    print("警告：没有订阅者接收到消息！")
else:
    print("成功：消息已被订阅者接收")