"""
测试Redis channel命名规则
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from utils import load_config
from redis_messenger import RedisMessenger

def test_channel_naming():
    """测试channel命名规则"""
    print("=" * 60)
    print("测试Redis Channel命名规则")
    print("=" * 60)
    
    # 加载配置
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    config = load_config(config_path)
    
    # 获取账户名称
    account_a_name = config['accounts']['account_a'].get('account_name', 'account_a')
    account_b_name = config['accounts']['account_b'].get('account_name', 'account_b')
    
    print(f"\n从配置文件读取:")
    print(f"  account_a_name: {account_a_name}")
    print(f"  account_b_name: {account_b_name}")
    
    # 创建RedisMessenger实例
    redis_config = config['redis']
    messenger = RedisMessenger(
        host=redis_config['host'],
        port=redis_config['port'],
        db=redis_config['db'],
        account_a_name=account_a_name,
        account_b_name=account_b_name
    )
    
    print(f"\nRedis Channel配置:")
    print(f"  CHANNEL_A_FILLED: {messenger.CHANNEL_A_FILLED}")
    print(f"  预期格式: hedge:{account_a_name}_to_{account_b_name}")
    print(f"  预期值: hedge:{account_a_name}_to_{account_b_name}")
    
    # 验证
    expected_channel = f"hedge:{account_a_name}_to_{account_b_name}"
    if messenger.CHANNEL_A_FILLED == expected_channel:
        print(f"\n✅ Channel命名正确!")
    else:
        print(f"\n❌ Channel命名错误!")
        print(f"  实际: {messenger.CHANNEL_A_FILLED}")
        print(f"  预期: {expected_channel}")
    
    print("=" * 60)

if __name__ == "__main__":
    test_channel_naming()