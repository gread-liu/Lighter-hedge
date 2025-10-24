#!/bin/bash

echo "===================================="
echo "停止对冲策略进程"
echo "===================================="
echo ""

# 进入hedge_strategy目录
cd "$(dirname "$0")"

# 读取PID文件
if [ -f .pid_A ]; then
    A_PID=$(cat .pid_A)
    echo "停止A入口进程 (PID: $A_PID)..."
    kill $A_PID 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "✓ A入口进程已停止"
    else
        echo "✗ A入口进程可能已经停止"
    fi
    rm .pid_A
else
    echo "未找到A入口PID文件"
fi

echo ""

if [ -f .pid_B ]; then
    B_PID=$(cat .pid_B)
    echo "停止B入口进程 (PID: $B_PID)..."
    kill $B_PID 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "✓ B入口进程已停止"
    else
        echo "✗ B入口进程可能已经停止"
    fi
    rm .pid_B
else
    echo "未找到B入口PID文件"
fi

echo ""
echo "===================================="
echo "所有进程已停止"
echo "===================================="