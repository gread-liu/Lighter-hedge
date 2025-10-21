# 跨账户对冲策略系统

## 简介

这是一个自动化的跨账户对冲策略系统，实现以下功能：

1. **A账户**（做多）：在订单簿指定档位挂限价买单
2. **订单监控**：实时监控A账户订单状态（轮询方式）
3. **Redis通信**：A账户完全成交后通过Redis发送消息
4. **B账户**（做空）：收到消息后立即市价卖单对冲
5. **循环执行**：B账户成交后，A账户继续挂新单

## 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        对冲策略循环                                │
│                                                                 │
│  A账户挂买单 → 监控成交 → Redis通知 → B账户卖单 → Redis确认 → 循环  │
└─────────────────────────────────────────────────────────────────┘
```

## 目录结构

```
hedge_strategy/
├── __init__.py              # 包初始化
├── main.py                  # 主程序入口
├── config.yaml              # 配置文件（需修改）
├── redis_messenger.py       # Redis消息管理
├── account_a_manager.py     # A账户管理器
├── account_b_manager.py     # B账户管理器
├── utils.py                 # 工具函数
├── requirements.txt         # 依赖库
└── README.md                # 本文档
```

## 安装步骤

### 1. 安装Redis

**Windows:**
```bash
# 下载Redis for Windows或使用Docker
docker run -d -p 6379:6379 redis
```

**Linux/Mac:**
```bash
sudo apt-get install redis-server  # Ubuntu/Debian
brew install redis                  # macOS
redis-server
```

### 2. 安装Python依赖

```bash
# 安装策略依赖
cd hedge_strategy
pip install -r requirements.txt

# 安装lighter SDK依赖
cd ../temp_lighter
pip install -r requirements.txt
```

## 配置

编辑 `config.yaml` 文件：

```yaml
accounts:
  account_a:
    api_key_private_key: "0x..."  # A账户私钥
    account_index: 65              # A账户索引
    api_key_index: 1               # API密钥索引

  account_b:
    api_key_private_key: "0x..."  # B账户私钥
    account_index: 66              # B账户索引
    api_key_index: 1

redis:
  host: "localhost"
  port: 6379
  db: 0

lighter:
  base_url: "https://testnet.zklighter.elliot.ai"  # 或 mainnet

strategy:
  retry_times: 3           # B账户对冲失败重试次数
  poll_interval: 1         # 订单状态轮询间隔(秒)
  ws_reconnect_delay: 5    # WebSocket重连延迟(秒)
```

## 使用方法

### 启动命令

```bash
cd E:\lighter
python hedge_strategy/main.py --market ETH --quantity 100000 --depth 1
```

### 参数说明

- `--market`: 市场名称（如 `ETH`, `BTC`, `ENA`）
- `--quantity`: 挂单数量（base_amount，整数）
- `--depth`: 挂单档位（1表示买1/卖1价格，2表示买2/卖2价格）
- `--config`: 配置文件路径（可选，默认 `hedge_strategy/config.yaml`）

### 运行示例

**示例1：ETH，10万数量，买1价挂单**
```bash
python hedge_strategy/main.py --market ETH --quantity 100000 --depth 1
```

**示例2：BTC，5万数量，买2价挂单**
```bash
python hedge_strategy/main.py --market BTC --quantity 50000 --depth 2
python hedge_strategy/main.py --market ENA --quantity 23 --depth 1
```

## 工作流程

### 详细步骤

1. **初始化阶段**
   - 加载配置文件
   - 连接Redis服务器
   - 初始化A、B账户的lighter客户端
   - 查询市场索引（根据市场名称）
   - 清理历史挂单
   - 设置Redis订阅

2. **循环执行**
   
   **第1步：A账户挂限价买单**
   - 查询订单簿买N档价格
   - 在该价格挂限价买单
   - 记录订单索引
   
   **第2步：监控订单状态**
   - 每1秒轮询订单状态
   - 检查 `status == "filled"` 且 `filled_amount == initial_amount`
   - 完全成交后发送Redis消息到 `hedge:account_a_filled`
   
   **第3步：B账户接收并对冲**
   - B账户监听Redis channel
   - 收到A账户成交消息
   - 立即创建市价卖单（数量与A账户一致）
   - 重试机制（最多3次）
   - 成交后发送Redis消息到 `hedge:account_b_filled`
   
   **第4步：等待确认**
   - A账户监听Redis channel
   - 收到B账户成交确认
   - 返回第1步，继续下一轮

3. **异常处理**
   - 捕获 `Ctrl+C` 信号
   - 取消所有未成交挂单
   - 关闭Redis连接
   - 关闭API客户端

## Redis消息格式

### Channel

- `hedge:account_a_filled` - A账户成交通知
- `hedge:account_b_filled` - B账户成交通知

### 消息内容（JSON）

```json
{
  "account_index": 65,
  "market_index": 0,
  "order_index": 123456789,
  "filled_base_amount": "100000",
  "filled_quote_amount": "40500000",
  "avg_price": "405.00",
  "timestamp": 1698765432,
  "side": "buy"
}
```

## 日志输出

程序运行时会输出详细日志：

```
2025-10-21 15:30:00 [INFO] ============================================================
2025-10-21 15:30:00 [INFO] 跨账户对冲策略启动
2025-10-21 15:30:00 [INFO] 市场: ETH, 数量: 100000, 档位: 1
2025-10-21 15:30:00 [INFO] ============================================================
2025-10-21 15:30:01 [INFO] 加载配置文件...
2025-10-21 15:30:02 [INFO] 初始化Redis连接...
2025-10-21 15:30:03 [INFO] 找到市场 ETH, market_index=0
2025-10-21 15:30:04 [INFO] 初始化完成！
2025-10-21 15:30:05 [INFO] ============================================================
2025-10-21 15:30:05 [INFO] 开始第 1 轮循环
2025-10-21 15:30:05 [INFO] ============================================================
2025-10-21 15:30:06 [INFO] [步骤1] A账户创建限价买单...
2025-10-21 15:30:07 [INFO] 市场0 买1档价格: 3024.66
2025-10-21 15:30:08 [INFO] 限价买单创建成功: order_index=12345
2025-10-21 15:30:09 [INFO] [步骤2] 监控A账户订单状态...
...
```

## 安全注意事项

1. **私钥安全**：请妥善保管 `config.yaml` 中的私钥，不要上传到Git
2. **资金管理**：建议先在测试网测试，确认无误后再用于主网
3. **网络监控**：确保网络连接稳定，避免对冲失败
4. **Redis安全**：生产环境建议配置Redis密码
5. **异常告警**：关键错误会记录在日志中，建议设置监控

## 故障排查

### Redis连接失败
```
错误: Redis连接失败: Error 111 connecting to localhost:6379
解决: 检查Redis服务是否启动 (redis-server)
```

### 市场未找到
```
错误: 未找到市场: ETH
解决: 检查市场名称拼写，确认市场在交易所存在
```

### 对冲失败
```
错误: 对冲失败，已达到最大重试次数！
解决: 检查B账户余额、网络连接、市场流动性
```

## 停止程序

按 `Ctrl+C` 安全停止程序，系统会：
1. 停止接收新订单
2. 取消所有未成交挂单
3. 关闭所有连接
4. 记录最终状态

## 技术支持

如有问题，请查看日志文件或联系开发者。

## 版本信息

- 版本: 1.0.0
- 更新时间: 2025-10-21
- Python版本要求: >= 3.8

