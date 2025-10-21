# 快速开始指南

## 前置条件检查清单

在运行策略之前，请确保以下条件都已满足：

- [ ] Redis服务已安装并运行
- [ ] Python 3.8+ 已安装
- [ ] 已有两个lighter账户（A账户和B账户）
- [ ] 已获取两个账户的私钥和索引
- [ ] 两个账户都有足够的资金

## 5分钟快速启动

### 步骤1：安装依赖 (2分钟)

```bash
# 进入项目目录
cd E:\lighter

# 安装策略依赖
pip install -r hedge_strategy/requirements.txt

# 安装lighter SDK依赖
pip install -r temp_lighter/requirements.txt
```

### 步骤2：启动Redis (1分钟)

**方式1：使用Docker（推荐）**
```bash
docker run -d -p 6379:6379 --name redis redis
```

**方式2：直接启动**
```bash
# Windows: 下载Redis for Windows并启动
redis-server

# Linux/Mac
sudo systemctl start redis  # 或 brew services start redis
```

**验证Redis是否运行**
```bash
redis-cli ping
# 应该返回: PONG
```

### 步骤3：配置账户 (1分钟)

编辑 `hedge_strategy/config.yaml`：

```yaml
accounts:
  account_a:
    api_key_private_key: "0xYOUR_A_ACCOUNT_PRIVATE_KEY"  # ← 修改这里
    account_index: 65                                     # ← 修改这里
    api_key_index: 1

  account_b:
    api_key_private_key: "0xYOUR_B_ACCOUNT_PRIVATE_KEY"  # ← 修改这里
    account_index: 66                                     # ← 修改这里
    api_key_index: 1

redis:
  host: "localhost"
  port: 6379
  db: 0

lighter:
  base_url: "https://testnet.zklighter.elliot.ai"  # 测试网

strategy:
  retry_times: 3
  poll_interval: 1
  ws_reconnect_delay: 5
```

### 步骤4：启动策略 (1分钟)

```bash
cd E:\lighter
python hedge_strategy/main.py --market ETH --quantity 100000 --depth 1
```

## 预期输出

启动后，您应该看到类似的日志输出：

```
2025-10-21 15:30:00 [INFO] ============================================================
2025-10-21 15:30:00 [INFO] 跨账户对冲策略启动
2025-10-21 15:30:00 [INFO] 市场: ETH, 数量: 100000, 档位: 1
2025-10-21 15:30:00 [INFO] ============================================================
2025-10-21 15:30:01 [INFO] 加载配置文件...
2025-10-21 15:30:02 [INFO] 初始化Redis连接...
2025-10-21 15:30:02 [INFO] Redis连接成功
2025-10-21 15:30:03 [INFO] 初始化A账户...
2025-10-21 15:30:04 [INFO] 初始化B账户...
2025-10-21 15:30:05 [INFO] 找到市场 ETH, market_index=0
2025-10-21 15:30:06 [INFO] 清理历史挂单...
2025-10-21 15:30:07 [INFO] 初始化完成！
2025-10-21 15:30:08 [INFO] ============================================================
2025-10-21 15:30:08 [INFO] 开始第 1 轮循环
2025-10-21 15:30:08 [INFO] ============================================================
2025-10-21 15:30:09 [INFO] [步骤1] A账户创建限价买单...
2025-10-21 15:30:10 [INFO] 市场0 买1档价格: 3024.66
2025-10-21 15:30:11 [INFO] 创建限价买单: price=3024.66, amount=100000
2025-10-21 15:30:12 [INFO] 限价买单创建成功: order_index=12345, client_order_index=1729504212000
2025-10-21 15:30:13 [INFO] [步骤2] 监控A账户订单状态...
2025-10-21 15:30:14 [INFO] 开始监控订单: order_index=12345
2025-10-21 15:30:15 [INFO] 订单状态: open, 成交量: 0/100000
2025-10-21 15:30:16 [INFO] 订单状态: open, 成交量: 50000/100000
2025-10-21 15:30:17 [INFO] 订单状态: filled, 成交量: 100000/100000
2025-10-21 15:30:17 [INFO] 订单完全成交！
2025-10-21 15:30:18 [INFO] 发布消息到 hedge:account_a_filled: {...}
2025-10-21 15:30:18 [INFO] 已发送A账户成交通知到Redis
2025-10-21 15:30:19 [INFO] [步骤3] 等待B账户对冲完成...
2025-10-21 15:30:19 [INFO] 等待B账户成交通知...
2025-10-21 15:30:20 [INFO] 收到A账户成交通知: {...}
2025-10-21 15:30:21 [INFO] 开始执行对冲: market=0, amount=100000
2025-10-21 15:30:22 [INFO] 创建市价卖单: amount=100000
2025-10-21 15:30:23 [INFO] 市价卖单创建成功: order_index=12346
2025-10-21 15:30:25 [INFO] 市价卖单已成交: filled_amount=100000
2025-10-21 15:30:26 [INFO] 对冲成功 (尝试 1/3)
2025-10-21 15:30:27 [INFO] 发布消息到 hedge:account_b_filled: {...}
2025-10-21 15:30:27 [INFO] 已发送B账户成交通知到Redis
2025-10-21 15:30:28 [INFO] 收到B账户成交通知: {...}
2025-10-21 15:30:29 [INFO] B账户成交确认，准备继续挂单
2025-10-21 15:30:30 [INFO] 第 1 轮完成，准备下一轮...
```

## 工作流程验证

策略运行时会执行以下循环：

1. ✅ **A账户挂单** - 在买1档价格挂限价买单
2. ✅ **监控成交** - 每秒检查订单状态
3. ✅ **Redis通知** - 完全成交后发送消息
4. ✅ **B账户对冲** - 收到消息后市价卖单
5. ✅ **确认循环** - B成交后，A继续挂新单

## 停止策略

按 `Ctrl+C` 安全停止，系统会自动：
- 停止接收新订单
- 取消所有未成交挂单
- 关闭所有连接

## 常见问题

### Q1: Redis连接失败
```
错误: Redis连接失败
```
**解决方案：**
```bash
# 检查Redis是否运行
redis-cli ping

# 如果没有运行，启动Redis
redis-server
```

### Q2: 市场未找到
```
错误: 未找到市场: ETH
```
**解决方案：**
- 检查市场名称拼写（大小写敏感）
- 确认该市场在交易所存在
- 测试网和主网的市场可能不同

### Q3: 订单创建失败
```
错误: 创建订单失败: code=400
```
**解决方案：**
- 检查账户余额是否充足
- 检查订单数量是否符合最小限制
- 检查私钥和账户索引是否正确

### Q4: 对冲失败
```
错误: 对冲失败，已达到最大重试次数
```
**解决方案：**
- 检查B账户余额
- 检查网络连接
- 检查市场流动性
- 增加 `retry_times` 配置

## 参数调整建议

### 小额测试（推荐新手）
```bash
python hedge_strategy/main.py --market ETH --quantity 10000 --depth 1
```

### 中等数量
```bash
python hedge_strategy/main.py --market ETH --quantity 100000 --depth 1
```

### 使用第2档价格（更容易成交）
```bash
python hedge_strategy/main.py --market ETH --quantity 100000 --depth 2
```

## 监控Redis消息（调试用）

打开新的终端窗口，监控Redis消息：

```bash
redis-cli
> SUBSCRIBE hedge:account_a_filled hedge:account_b_filled
```

您会看到实时的成交消息。

## 下一步

- 阅读 [README.md](README.md) 了解详细架构
- 调整 `config.yaml` 中的策略参数
- 在测试网充分测试后再使用主网
- 设置日志监控和告警

## 技术支持

如遇问题，请：
1. 检查日志输出
2. 确认所有前置条件
3. 查看 [README.md](README.md) 故障排查部分

