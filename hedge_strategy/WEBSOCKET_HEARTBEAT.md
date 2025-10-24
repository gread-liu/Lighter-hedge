# WebSocket心跳机制实现说明

## 概述

为了保持A账户的WebSocket连接稳定，避免长时间无消息导致连接断开，我们实现了双重心跳保障机制：
1. **主动心跳监控**：定期检查连接状态，超时则触发重连
2. **Ping/Pong响应**：收到服务器ping时主动回复pong，保持连接活跃

## 实现原理

### 1. Ping/Pong响应机制

当收到服务器发送的ping消息时，客户端会主动回复pong响应，告知服务器连接仍然活跃。

**实现位置**：[`account_a_manager.py`](account_a_manager.py:674-688)

```python
# 处理ping消息 - 主动回复pong保持连接
if isinstance(account_data, dict) and account_data.get('type') == 'ping':
    logging.debug("收到WebSocket ping消息，回复pong")
    try:
        # 发送pong响应
        if self.ws_client and self.ws_client.ws:
            import json
            pong_message = json.dumps({"type": "pong"})
            self.ws_client.ws.send(pong_message)
            logging.debug("已发送pong响应")
    except Exception as pong_err:
        logging.warning(f"发送pong响应失败: {pong_err}")
    return
```

**工作原理**：
- 服务器定期发送 `{"type": "ping"}` 消息
- 客户端收到后立即回复 `{"type": "pong"}` 消息
- 这样服务器知道客户端仍然在线，不会主动断开连接

### 2. 心跳监控线程

在 [`account_a_manager.py`](account_a_manager.py) 中添加了独立的心跳监控线程 `_ws_heartbeat_monitor()`，该线程会：

- **定期检查**：每30秒检查一次WebSocket连接状态
- **超时检测**：如果90秒内未收到任何消息，认为连接可能已断开
- **主动重连**：检测到超时后，主动关闭当前连接，触发重连机制

### 2. 消息时间戳追踪

添加了 `last_ws_message_time` 变量来追踪最后一次收到WebSocket消息的时间：

```python
self.last_ws_message_time = time.time()  # 初始化
```

每次收到WebSocket消息时（包括ping消息），都会更新这个时间戳：

```python
def _on_account_update(self, account_id: str, account_data: Dict[str, Any]):
    # 更新最后收到消息的时间
    self.last_ws_message_time = time.time()
    ...
```

### 3. 心跳参数配置

| 参数 | 值 | 说明 |
|-----|-----|-----|
| `heartbeat_interval` | 30秒 | 心跳检查间隔 |
| `timeout_threshold` | 90秒 | 超时阈值（3倍心跳间隔） |

## 工作流程

```
启动WebSocket
    ↓
启动心跳监控线程
    ↓
每30秒检查一次
    ↓
计算距上次消息的时间
    ↓
    ├─ < 90秒 → 记录日志，继续监控
    └─ ≥ 90秒 → 判定超时
                  ↓
              关闭当前连接
                  ↓
              触发重连机制
                  ↓
              指数退避重试
```

## 关键代码位置

### 1. 初始化（第66-72行）

```python
# WebSocket相关
self.ws_client: Optional[WsClient] = None
self.ws_thread: Optional[threading.Thread] = None
self.ws_heartbeat_thread: Optional[threading.Thread] = None
self.ws_running = False
self.pending_orders = {}
self.last_ws_message_time = time.time()
```

### 2. 启动心跳线程（第551-568行）

```python
# 启动心跳线程
self.ws_heartbeat_thread = threading.Thread(
    target=self._ws_heartbeat_monitor,
    daemon=True
)
self.ws_heartbeat_thread.start()
```

### 3. 心跳监控逻辑（第767-802行）

```python
def _ws_heartbeat_monitor(self):
    """WebSocket心跳监控线程"""
    heartbeat_interval = 30  # 心跳间隔（秒）
    timeout_threshold = 90  # 超时阈值（秒）
    
    while self.ws_running:
        time.sleep(heartbeat_interval)
        
        time_since_last_message = time.time() - self.last_ws_message_time
        
        if time_since_last_message > timeout_threshold:
            # 触发重连
            if self.ws_client and self.ws_client.ws:
                self.ws_client.ws.close()
```

### 4. 更新消息时间戳（第662行）

```python
def _on_account_update(self, account_id: str, account_data: Dict[str, Any]):
    # 更新最后收到消息的时间
    self.last_ws_message_time = time.time()
```

## 与现有重连机制的配合

心跳机制与现有的指数退避重连机制完美配合：

1. **心跳监控**：主动检测连接是否存活
2. **指数退避**：连接断开后智能重试
3. **双重保障**：
   - 如果服务器主动断开 → 指数退避重连
   - 如果连接僵死无响应 → 心跳检测触发重连

## 日志输出

### 正常运行

```
WebSocket心跳监控已启动: 间隔=30s, 超时阈值=90s
WebSocket心跳检查: 距上次消息 25.3秒
WebSocket心跳检查: 距上次消息 55.7秒
```

### 检测到超时

```
WebSocket连接可能已断开（92.5秒未收到消息），尝试重新连接...
WebSocket连接断开（连续失败1次），2秒后重试...
WebSocket开始连接...
```

## 优势

1. **主动监控**：不等待连接完全断开才发现问题
2. **快速恢复**：及时检测并触发重连，减少停机时间
3. **资源友好**：30秒检查一次，不会造成性能负担
4. **可配置**：心跳间隔和超时阈值可根据需要调整
5. **日志完善**：详细记录连接状态，便于问题排查

## 注意事项

1. **心跳间隔不宜过短**：避免频繁检查造成资源浪费
2. **超时阈值应合理**：建议设置为心跳间隔的3倍
3. **与服务器ping配合**：如果服务器定期发送ping消息，心跳机制会自动更新时间戳
4. **线程安全**：心跳线程与主线程独立运行，互不干扰

## 测试建议

1. **正常场景**：观察心跳日志是否正常输出
2. **网络中断**：模拟网络断开，验证是否能自动重连
3. **长时间运行**：运行数小时，确认连接稳定性
4. **高负载**：在订单频繁成交时，验证心跳不受影响

## 双重保障机制

### Ping/Pong响应（被动）
- **触发条件**：收到服务器ping消息
- **响应方式**：立即发送pong
- **作用**：告知服务器客户端在线，防止服务器主动断开

### 心跳监控（主动）
- **触发条件**：90秒未收到任何消息
- **响应方式**：主动关闭连接并重连
- **作用**：检测连接僵死，快速恢复

### 配合效果
1. **正常情况**：服务器定期ping → 客户端回复pong → 连接保持
2. **网络抖动**：短暂断开 → 指数退避重连 → 恢复正常
3. **连接僵死**：90秒无消息 → 心跳检测触发 → 主动重连

## 日志示例

### Ping/Pong交互
```
收到WebSocket ping消息，回复pong
已发送pong响应
```

### 心跳检查
```
WebSocket心跳检查: 距上次消息 25.3秒
```

### 超时重连
```
WebSocket连接可能已断开（92.5秒未收到消息），尝试重新连接...
```

## 修改历史

- 2025-01-24 12:08 (UTC+8) - 初始实现心跳监控机制
- 2025-01-24 12:27 (UTC+8) - 添加Ping/Pong响应机制