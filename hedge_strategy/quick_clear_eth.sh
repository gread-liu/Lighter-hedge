#!/bin/bash

# 快速清空ETH市场的A和B账户
# 使用方法: ./quick_clear_eth.sh

echo "=========================================="
echo "开始清空ETH市场的A和B账户"
echo "=========================================="

cd "$(dirname "$0")"

# 执行清空程序，指定ETH市场
python3 clear_accounts.py --market ETH --account all

echo ""
echo "=========================================="
echo "清空完成！"
echo "=========================================="