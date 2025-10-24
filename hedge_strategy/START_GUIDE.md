# 对冲策略启动指南

## 架构说明

本系统采用双进程架构，通过Redis进行进程间通信：

- **A入口进程（main_A.py）**：刷量程序A，负责挂限价单并监控成交
- **B入口进程（main_B.py）**：刷量程序B，订阅A的成交消息并执行市价对冲

## 前置条件

1. **Redis服务**必须已启动
   ```bash
   # Windows
   cd redis/Redis-7.2.4-Windows-x64-msys2
   ./redis-server.exe redis.conf
   
   # 或使用start.bat
   start.bat
   ```

2. **配置文件**已正确设置（config.yaml）
   - account_a: A账户的私钥和索引
   - account_b: B账户的私钥和索引
   - redis: Redis连接配置

## 启动步骤

### 方式一：分别启动（推荐用于生产环境）

#### 1. 启动B入口进程（订阅者）
```bash
# 在终端1中启动B入口
cd hedge_strategy
python main_B.py --market ETH --config config.yaml
```

**说明**：
- B入口会进入监听模式，等待A账户的成交通知
- 收到通知后自动执行市价对冲
- 参数：
  - `--market`: 市场名称（ETH, BTC, ENA等）
  - `--config`: 配置文件路径（可选，默认为当前目录的config.yaml）

#### 2. 启动A入口进程（发布者）
```bash
# 在终端2中启动A入口
cd hedge_strategy
python main_A.py --market ETH --quantity 0.01 --depth 1 --config config.yaml
```

**说明**：
- A入口会循环执行限价挂单逻辑
- 订单成交后通过Redis通知B入口
- 参数：
  - `--market`: 市场名称（ETH, BTC, ENA等）
  - `--quantity`: 挂单数量
  - `--depth`: 挂单档位（1表示买1/卖1）
  - `--config`: 配置文件路径（可选）

### 方式二：使用启动脚本

#### Windows批处理脚本
创建 `start_hedge.bat`：
```batch
@echo off
echo 启动对冲策略...

REM 启动B入口（订阅者）
start "B入口-订阅" cmd /k "cd hedge_strategy && python main_B.py --market ETH"

REM 等待2秒确保B入口已启动
timeout /t 2

REM 启动A入口（发布者）
start "A入口-挂单" cmd /k "cd hedge_strategy && python main_A.py --market ETH --quantity 0.01 --depth 1"

echo 两个进程已启动
pause
```

#### Linux/Mac Shell脚本
创建 `start_hedge.sh`：
```bash
#!/bin/bash
echo "启动对冲策略..."

# 启动B入口（订阅者）
cd hedge_strategy
python main_B.py --market ETH --config config.yaml &
B_PID=$!
echo "B入口进程已启动，PID: $B_PID"

# 等待2秒确保B入口已启动
sleep 2

# 启动A入口（发布者）
python main_A.py --market ETH --quantity 0.01 --depth 1 --config config.yaml &
A_PID=$!
echo "A入口进程已启动，PID: $A_PID"

echo "两个进程已启动"
echo "A入口 PID: $A_PID"
echo "B入口 PID: $B_PID"

# 等待进程
wait
```

## 工作流程

```
┌─────────────────────────────────────────────────────────────┐
│                      对冲策略工作流程                          │
└─────────────────────────────────────────────────────────────┘

A入口进程（main_A.py）                    B入口进程（main_B.py）
     │                                           │
     │ 1. 查询持仓和活跃单                        │ 监听Redis消息
     ├──────────────────────────────────────────┤
     │ 2. 根据状态挂限价单                        │ 等待中...
     │    - 无持仓无活跃单 → 限价开多              │
     │    - 有持仓无活跃单 → 限价平多              │
     ├──────────────────────────────────────────┤
     │ 3. 订单成交                                │
     │    ↓                                      │
     │ 4. 推送成交信息到Redis                     │
     │    ────────────────────────────────────→  │
     │                                           │ 5. 收到成交通知
     │                                           │    ↓
     │                                           │ 6. 执行市价对冲
     │                                           │    ↓
     │                                           │ 7. 推送对冲完成
     │  ←────────────────────────────────────    │
     │ 8. 收到对冲完成通知                        │
     │    ↓                                      │
     │ 9. 继续下一轮                              │ 继续监听...
     │                                           │
```

## 监控和日志

### 查看日志
两个进程都会输出详细的日志信息：
- A入口：显示挂单、成交、推送消息等信息
- B入口：显示订阅、收到消息、对冲执行等信息

### Redis监控
可以使用Redis CLI监控消息：
```bash
# 监控所有发布的消息
redis-cli -p 6388
> PSUBSCRIBE hedge:*

# 查看特定channel
> SUBSCRIBE hedge:account_a_filled
> SUBSCRIBE hedge:account_b_filled
```

## 停止策略

### 优雅停止
在各自的终端中按 `Ctrl+C`，程序会：
1. 停止监听/挂单
2. 取消所有活跃订单
3. 关闭Redis连接
4. 清理资源

### 强制停止
```bash
# Linux/Mac
pkill -f main_A.py
pkill -f main_B.py

# Windows
taskkill /F /IM python.exe
```

## 故障排查

### 问题1：B入口收不到消息
- 检查Redis是否正常运行
- 确认config.yaml中的Redis配置正确
- 确保B入口先于A入口启动

### 问题2：对冲失败
- 检查B账户余额是否充足
- 查看日志中的具体错误信息
- 确认市场流动性是否充足

### 问题3：Nonce错误
- 程序会自动重试3次
- 如果持续出现，检查网络连接
- 确认没有其他程序同时使用相同账户

## 配置参数说明

### config.yaml关键参数
```yaml
lighter:
  maker_order_time_out: 30  # 限价单超时时间（秒）

strategy:
  retry_times: 3            # 对冲失败重试次数
  poll_interval: 1          # 订单状态轮询间隔（秒）
```

## 注意事项

1. **启动顺序**：建议先启动B入口（订阅者），再启动A入口（发布者）
2. **独立部署**：A和B应该部署在不同的服务器/IP上
3. **账户隔离**：A和B必须使用不同的账户
4. **监控告警**：建议配置监控系统，及时发现异常
5. **资金管理**：确保两个账户都有充足的余额

## 测试建议

### 小额测试
```bash
# 使用小额进行测试
python main_A.py --market ETH --quantity 0.001 --depth 1
```

### 模拟环境
如果有测试网，建议先在测试网验证整个流程。