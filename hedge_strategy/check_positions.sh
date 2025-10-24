#!/bin/bash

echo "======================================"
echo "查看A、B账户仓位"
echo "======================================"
echo ""

echo "Redis中的持仓数据:"
redis-cli -p 6388 HGETALL hedge:positions:account_4_account_5:BTC

echo ""
echo "======================================"