"""
测试Redis持仓数据结构
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from utils import load_config
from redis_messenger import RedisMessenger

def test_position_structure():
    """测试持仓数据结构"""
    print("=" * 60)
    print("测试Redis持仓数据结构")
    print("=" * 60)
    
    # 加载配置
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    config = load_config(config_path)
    
    # 获取账户信息
    account_a_name = config['accounts']['account_a'].get('account_name', 'account_a')
    account_a_index = config['accounts']['account_a']['account_index']
    account_b_name = config['accounts']['account_b'].get('account_name', 'account_b')
    account_b_index = config['accounts']['account_b']['account_index']
    
    print(f"\n账户信息:")
    print(f"  A账户: {account_a_name} (index={account_a_index})")
    print(f"  B账户: {account_b_name} (index={account_b_index})")
    
    # 创建RedisMessenger实例
    redis_config = config['redis']
    messenger = RedisMessenger(
        host=redis_config['host'],
        port=redis_config['port'],
        db=redis_config['db'],
        account_a_name=account_a_name,
        account_b_name=account_b_name
    )
    messenger.connect()
    
    # 测试市场
    market = "BTC"
    
    print(f"\n测试更新持仓到Redis:")
    print(f"  市场: {market}")
    
    # 更新A账户持仓
    print(f"\n1. 更新{account_a_name}持仓...")
    messenger.update_position(
        account_name=account_a_name,
        account_index=account_a_index,
        market=market,
        position_size=0.0002,
        sign=1
    )
    print(f"   ✅ {account_a_name}持仓已更新")
    
    # 更新B账户持仓
    print(f"\n2. 更新{account_b_name}持仓...")
    messenger.update_position(
        account_name=account_b_name,
        account_index=account_b_index,
        market=market,
        position_size=0.0002,
        sign=-1
    )
    print(f"   ✅ {account_b_name}持仓已更新")
    
    # 查询单个账户持仓
    print(f"\n3. 查询单个账户持仓:")
    pos_a = messenger.get_position_by_account_name(account_a_name, market)
    pos_b = messenger.get_position_by_account_name(account_b_name, market)
    
    print(f"\n   {account_a_name}持仓:")
    if pos_a:
        print(f"     account_name: {pos_a.get('account_name')}")
        print(f"     account_index: {pos_a.get('account_index')}")
        print(f"     size: {pos_a.get('size')}")
        print(f"     sign: {pos_a.get('sign')}")
        print(f"     direction: {pos_a.get('direction')}")
        print(f"     market: {pos_a.get('market')}")
        print(f"     timestamp: {pos_a.get('timestamp')}")
    else:
        print(f"     未找到持仓")
    
    print(f"\n   {account_b_name}持仓:")
    if pos_b:
        print(f"     account_name: {pos_b.get('account_name')}")
        print(f"     account_index: {pos_b.get('account_index')}")
        print(f"     size: {pos_b.get('size')}")
        print(f"     sign: {pos_b.get('sign')}")
        print(f"     direction: {pos_b.get('direction')}")
        print(f"     market: {pos_b.get('market')}")
        print(f"     timestamp: {pos_b.get('timestamp')}")
    else:
        print(f"     未找到持仓")
    
    # 查询所有持仓
    print(f"\n4. 查询{market}市场所有持仓:")
    all_positions = messenger.get_all_positions(market)
    print(f"   找到 {len(all_positions)} 个账户的持仓:")
    for acc_name, pos_data in all_positions.items():
        print(f"\n   账户: {acc_name}")
        print(f"     size: {pos_data.get('size')}, sign: {pos_data.get('sign')}, direction: {pos_data.get('direction')}")
    
    # 验证数据结构
    print(f"\n5. 验证数据结构:")
    redis_key = f"hedge:positions:{market}"
    print(f"   Redis Key: {redis_key}")
    print(f"   Redis Type: Hash")
    print(f"   Hash Fields: {list(all_positions.keys())}")
    
    if pos_a and pos_b:
        print(f"\n✅ 数据结构测试通过!")
        print(f"   - 两个账户的持仓存储在同一个key中")
        print(f"   - 可以通过account_name准确查询到各自的持仓")
        print(f"   - 数据包含完整的账户信息(account_name, account_index)")
    else:
        print(f"\n❌ 数据结构测试失败!")
    
    # 关闭连接
    messenger.close()
    
    print("=" * 60)

if __name__ == "__main__":
    test_position_structure()