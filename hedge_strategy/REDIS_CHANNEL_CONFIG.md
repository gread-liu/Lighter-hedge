# Redis Channel 配置说明

## 概述

Redis channel的命名规则已改为可配置,基于配置文件中的账户名称动态生成。

## 命名规则

**格式**: `hedge:{account_a_name}_to_{account_b_name}`

其中:
- `account_a_name`: 来自配置文件 `accounts.account_a.account_name`
- `account_b_name`: 来自配置文件 `accounts.account_b.account_name`

## 示例

### 配置文件 (config.yaml)

```yaml
accounts:
  account_a:
    account_name: account_4
    api_key_private_key: "..."
    account_index: 280459
    api_key_index: 3

  account_b:
    account_name: account_5
    api_key_private_key: "..."
    account_index: 280458
    api_key_index: 2
```

### 生成的Channel名称

```
hedge:account_4_to_account_5
```

## 代码实现

### RedisMessenger初始化

```python
# 从配置文件读取账户名称
account_a_name = config['accounts']['account_a'].get('account_name', 'account_a')
account_b_name = config['accounts']['account_b'].get('account_name', 'account_b')

# 创建RedisMessenger实例
redis_messenger = RedisMessenger(
    host=redis_config['host'],
    port=redis_config['port'],
    db=redis_config['db'],
    account_a_name=account_a_name,
    account_b_name=account_b_name
)
```

### RedisMessenger类

```python
class RedisMessenger:
    def __init__(self, host: str = "localhost", port: int = 6379, db: int = 0, 
                 account_a_name: str = None, account_b_name: str = None):
        # 动态设置channel名称
        if account_a_name and account_b_name:
            self.CHANNEL_A_FILLED = f"hedge:{account_a_name}_to_{account_b_name}"
        else:
            self.CHANNEL_A_FILLED = "hedge:account_a_filled"  # 默认值
```

## 优势

1. **灵活性**: 可以通过修改配置文件轻松更改channel名称
2. **可读性**: Channel名称清晰表达了消息流向 (从account_a到account_b)
3. **多实例支持**: 不同的账户对可以使用不同的channel,避免冲突
4. **向后兼容**: 如果配置文件中没有account_name,会使用默认值

## 测试

运行测试脚本验证channel命名:

```bash
python3 hedge_strategy/test_redis_channel.py
```

预期输出:
```
✅ Channel命名正确!
CHANNEL_A_FILLED: hedge:account_4_to_account_5
```

## 相关文件

- `hedge_strategy/redis_messenger.py` - RedisMessenger类实现
- `hedge_strategy/main_A.py` - A账户主程序,初始化RedisMessenger
- `hedge_strategy/main_B.py` - B账户主程序,初始化RedisMessenger
- `hedge_strategy/config.yaml` - 配置文件,包含account_name
- `hedge_strategy/test_redis_channel.py` - 测试脚本

## 注意事项

1. 确保配置文件中的`account_name`字段已正确设置
2. A账户和B账户必须使用相同的配置文件,以确保channel名称一致
3. 修改`account_name`后需要重启系统才能生效