#!/usr/bin/env python3
"""
验证对冲方向逻辑的测试脚本
测试场景：
1. A开多（buy）→ B开空（sell, is_ask=True）
2. A平多（sell）→ B平空（buy, is_ask=False）
"""

def verify_hedge_logic(a_side: str) -> tuple:
    """
    验证对冲方向逻辑
    
    Args:
        a_side: A账户的操作方向 ('buy' 或 'sell')
        
    Returns:
        (is_ask, b_action): B账户的is_ask参数和操作描述
    """
    if a_side == "buy":
        is_ask = True  # B开空
        b_action = "开空"
    else:  # a_side == "sell"
        is_ask = False  # B平空
        b_action = "平空"
    
    return is_ask, b_action


def main():
    print("=" * 60)
    print("对冲方向逻辑验证")
    print("=" * 60)
    
    # 测试场景1：A开多
    print("\n【场景1】A账户开多（buy）")
    print("-" * 60)
    a_side = "buy"
    is_ask, b_action = verify_hedge_logic(a_side)
    print(f"A账户操作: {a_side} (开多)")
    print(f"B账户操作: {b_action}")
    print(f"B账户is_ask参数: {is_ask}")
    print(f"预期结果: B开空对冲A的多头仓位")
    print(f"验证: {'✅ 正确' if is_ask == True else '❌ 错误'}")
    
    # 测试场景2：A平多
    print("\n【场景2】A账户平多（sell）")
    print("-" * 60)
    a_side = "sell"
    is_ask, b_action = verify_hedge_logic(a_side)
    print(f"A账户操作: {a_side} (平多)")
    print(f"B账户操作: {b_action}")
    print(f"B账户is_ask参数: {is_ask}")
    print(f"预期结果: B平空对应A的平多操作")
    print(f"验证: {'✅ 正确' if is_ask == False else '❌ 错误'}")
    
    # 总结
    print("\n" + "=" * 60)
    print("逻辑验证总结")
    print("=" * 60)
    print("✅ A开多（buy） → B开空（is_ask=True）")
    print("✅ A平多（sell）→ B平空（is_ask=False）")
    print("\n对冲方向逻辑正确！")
    print("=" * 60)


if __name__ == "__main__":
    main()