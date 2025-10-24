#!/bin/bash
# 快速清空A、B账户的脚本
# 功能：停止策略 → 清空账户 → 显示结果

echo "============================================================"
echo "快速清空A、B账户工具"
echo "============================================================"
echo ""

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

# 1. 停止策略
echo "【步骤1/3】停止A和B入口程序..."
echo "------------------------------------------------------------"

# 停止A入口
A_PID=$(ps aux | grep "main_A.py" | grep -v grep | awk '{print $2}')
if [ -n "$A_PID" ]; then
    kill -9 $A_PID 2>/dev/null
    echo "✅ A入口已停止 (PID: $A_PID)"
else
    echo "ℹ️  A入口未运行"
fi

# 停止B入口
B_PID=$(ps aux | grep "main_B.py" | grep -v grep | awk '{print $2}')
if [ -n "$B_PID" ]; then
    kill -9 $B_PID 2>/dev/null
    echo "✅ B入口已停止 (PID: $B_PID)"
else
    echo "ℹ️  B入口未运行"
fi

# 等待进程完全停止
echo ""
echo "等待进程完全停止..."
sleep 3

# 2. 清空账户
echo ""
echo "【步骤2/3】清空所有账户的订单和持仓..."
echo "------------------------------------------------------------"
python3 clear_accounts.py --account all --market BTC

# 3. 显示结果
echo ""
echo "【步骤3/3】清空完成"
echo "============================================================"
echo "✅ 清空流程已完成！"
echo ""
echo "提示："
echo "  - 如需重新启动策略，请运行: ./start_hedge.sh"
echo "  - 如需查看详细日志，请查看上方输出"
echo "============================================================"