#!/bin/bash

# 一键清空所有账户的持仓和订单
# 使用市价单快速平仓

cd "$(dirname "$0")"

echo "=================================="
echo "一键清空所有账户"
echo "=================================="
echo ""
echo "⚠️  警告：此操作将："
echo "  1. 取消所有活跃订单"
echo "  2. 使用市价单平掉所有持仓"
echo ""
read -p "确认执行？(y/N): " confirm

if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "已取消操作"
    exit 0
fi

echo ""
echo "开始执行清空操作..."
echo ""

python3 quick_clear_all.py

echo ""
echo "=================================="
echo "操作完成"
echo "=================================="