# Redis 数据结构说明

## 概述

系统使用Redis存储两类数据:
1. **持仓数据** - 使用Hash结构存储A和B账户的持仓信息
2. **消息通道** - 使用Pub/Sub模式进行账户间通信

## 1. 持仓数据结构

### Redis Key格式

```
hedge:positions:{account_a_name}_{account_b_name}:{MARKET}
```

例如:
- `hedge:positions:account_4_account_5:BTC` - account_4和account_5配对的BTC市场持仓
- `hedge:positions:account_4_account_5:ETH` - account_4和account_5配对的ETH市场持仓
- `hedge:positions:account_6_account_7:BTC` - account_6和account_7配对的BTC市场持仓

**优势**: 支持多个A-B账户配对同时运行,互不干扰

### 数据类型

**Hash** - 每个市场使用一个Hash,field为账户名称

### Hash结构

```
Key: hedge:positions:account_4_account_5:BTC
Type: Hash
Fields:
  - account_4: {"account_name": "account_4", "account_index": 280459, ...}
  - account_5: {"account_name": "account_5", "account_index": 280458, ...}
```

### 持仓数据格式

每个账户的持仓数据为JSON字符串:

```json
{
  "account_name": "account_4",
  "account_index": 280459,
  "size": 0.0002,
  "sign": 1,
  "direction": "long",
  "timestamp": 1761291173,
  "market": "BTC"
}
```

**字段说明**:
- `account_name`: 账户名称(来自配置文件)
- `account_index`: 账户索引
- `size`: 持仓大小(绝对值)
- `sign`: 持仓方向(1=多头, -1=空头, 0=无持仓)
- `direction`: 方向描述("long"/"short"/"none")
- `timestamp`: 持仓创建或更新时间戳
- `market`: 市场名称

### 优势

1. **统一存储**: A和B账户的持仓存储在同一个key中,便于查询和对比
2. **灵活查询**:
   - 可以查询单个账户: `HGET hedge:positions:account_4_account_5:BTC account_4`
   - 可以查询所有账户: `HGETALL hedge:positions:account_4_account_5:BTC`
3. **完整信息**: 包含account_name和account_index,便于追踪和调试
4. **多市场支持**: 不同市场使用不同的key,互不干扰
5. **多配对支持**: 不同的A-B账户配对使用不同的key,支持多实例部署

## 2. 消息通道

### Channel命名规则

```
hedge:{account_a_name}_to_{account_b_name}
```

例如: `hedge:account_4_to_account_5`

### 消息格式

A账户成交通知:
```json
{
  "account_index": 280459,
  "market_index": 1,
  "order_index": 844424540373959,
  "filled_base_amount": "0.00020",
  "filled_quote_amount": "22.231760",
  "avg_price": "111158.8",
  "timestamp": 1761290283,
  "side": "buy"
}
```

平仓信号:
```json
{
  "action": "close_all",
  "market": "BTC",
  "market_index": 1,
  "timestamp": 1761290500
}
```

## 3. 代码示例

### 更新持仓

```python
# 更新A账户持仓
redis_messenger.update_position(
    account_name="account_4",
    account_index=280459,
    market="BTC",
    position_size=0.0002,
    sign=1
)

# 更新B账户持仓
redis_messenger.update_position(
    account_name="account_5",
    account_index=280458,
    market="BTC",
    position_size=0.0002,
    sign=-1
)
```

### 查询持仓

```python
# 查询单个账户持仓
pos_a = redis_messenger.get_position_by_account_name("account_4", "BTC")
pos_b = redis_messenger.get_position_by_account_name("account_5", "BTC")

# 查询市场所有持仓
all_positions = redis_messenger.get_all_positions("BTC")
# 返回: {"account_4": {...}, "account_5": {...}}
```

### 发布消息

```python
# 发布A账户成交消息
message = RedisMessenger.create_filled_message(
    account_index=280459,
    market_index=1,
    order_index=844424540373959,
    filled_base_amount="0.00020",
    filled_quote_amount="22.231760",
    avg_price="111158.8",
    side="buy"
)
redis_messenger.publish_a_filled(message)
```

## 4. Redis命令示例

### 查看持仓数据

```bash
# 查看account_4和account_5配对的BTC市场所有持仓
redis-cli -p 6388 HGETALL hedge:positions:account_4_account_5:BTC

# 查看account_4的持仓
redis-cli -p 6388 HGET hedge:positions:account_4_account_5:BTC account_4

# 查看所有持仓key
redis-cli -p 6388 KEYS "hedge:positions:*"

# 查看特定配对的所有市场
redis-cli -p 6388 KEYS "hedge:positions:account_4_account_5:*"
```

### 监听消息

```bash
# 监听A到B的消息通道
redis-cli -p 6388 SUBSCRIBE hedge:account_4_to_account_5
```

## 5. 测试

### 测试持仓数据结构

```bash
python3 hedge_strategy/test_redis_positions.py
```

预期输出:
```
✅ 数据结构测试通过!
   - 两个账户的持仓存储在同一个key中
   - 可以通过account_name准确查询到各自的持仓
   - 数据包含完整的账户信息(account_name, account_index)
```

### 测试Channel命名

```bash
python3 hedge_strategy/test_redis_channel.py
```

## 6. 配置要求

确保配置文件中包含`account_name`字段:

```yaml
accounts:
  account_a:
    account_name: account_4  # 必需
    account_index: 280459
    api_key_index: 3
    api_key_private_key: "..."

  account_b:
    account_name: account_5  # 必需
    account_index: 280458
    api_key_index: 2
    api_key_private_key: "..."
```

## 7. 相关文件

- [`redis_messenger.py`](redis_messenger.py) - Redis操作封装
- [`main_A.py`](main_A.py) - A账户主程序
- [`main_B.py`](main_B.py) - B账户主程序
- [`test_redis_positions.py`](test_redis_positions.py) - 持仓数据结构测试
- [`test_redis_channel.py`](test_redis_channel.py) - Channel命名测试