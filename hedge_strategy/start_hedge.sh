#!/bin/bash

echo "===================================="
echo "启动对冲策略 - 双进程模式"
echo "===================================="
echo ""

# 检查Redis是否运行（检查6388端口）
echo "[1/3] 检查Redis服务..."
if redis-cli -p 6388 ping > /dev/null 2>&1; then
    echo "✓ Redis服务正在运行（端口6388）"
else
    echo "✗ Redis服务未运行或端口6388无法连接"
    echo "请确保Redis运行在6388端口"
    exit 1
fi
echo ""

# 进入hedge_strategy目录
cd "$(dirname "$0")"

# 启动B入口（订阅者）
echo "[2/3] 启动B入口进程（订阅模式）..."
python3 main_B.py --market BTC --config config.yaml > logs/main_B.log 2>&1 &
B_PID=$!
echo "✓ B入口进程已启动，PID: $B_PID"
echo ""

# 等待3秒确保B入口已启动并连接Redis
echo "等待B入口初始化..."
sleep 3
echo ""

# 启动A入口（发布者）
echo "[3/3] 启动A入口进程（挂单模式）..."
python3 main_A.py --market BTC --quantity 0.0002 --depth 60 --config config.yaml > logs/main_A.log 2>&1 &
A_PID=$!
echo "✓ A入口进程已启动，PID: $A_PID"
echo ""

echo "===================================="
echo "两个进程已成功启动！"
echo "===================================="
echo ""
echo "进程信息："
echo "- A入口 PID: $A_PID"
echo "- B入口 PID: $B_PID"
echo ""
echo "日志文件："
echo "- A入口: logs/main_A.log"
echo "- B入口: logs/main_B.log"
echo ""
echo "查看日志："
echo "  tail -f logs/main_A.log"
echo "  tail -f logs/main_B.log"
echo ""
echo "停止进程："
echo "  kill $A_PID $B_PID"
echo "  或运行: ./stop_hedge.sh"
echo ""

# 保存PID到文件
echo $A_PID > .pid_A
echo $B_PID > .pid_B

echo "PID已保存到 .pid_A 和 .pid_B"