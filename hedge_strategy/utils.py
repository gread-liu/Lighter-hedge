"""
工具函数模块
包含市场查询、价格解析等辅助功能
"""

import asyncio
import logging
import os
import sys
from decimal import Decimal
from typing import Optional, Dict, Any

from lighter import OrderBook

# 添加temp_lighter到路径以导入lighter模块
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'temp_lighter'))

import lighter


async def get_market_index_by_name(api_client: lighter.ApiClient, market_name: str) -> Optional[OrderBook]:
    """
    根据市场名称查询对应的market_index
    
    Args:
        api_client: lighter ApiClient客户端
        market_name: 市场名称，如 "ETH", "BTC"
    
    Returns:
        market_index，如果未找到则返回None
    """
    max_retries = 5
    retry_count = 0

    while retry_count < max_retries:
        try:
            # 创建OrderApi实例
            order_api = lighter.OrderApi(api_client)
            # 获取所有市场信息（market_id=255表示获取所有市场）
            order_books = await order_api.order_books(market_id=255)

            # 遍历所有市场找到匹配的symbol
            for order_book in order_books.order_books:
                if order_book.symbol.upper() == market_name.upper():
                    logging.info(f"找到市场 {market_name}, market_index={order_book.market_id}")
                    # return order_book.market_id
                    return order_book

            logging.error(f"未找到市场: {market_name}")
            return None

        except Exception as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                retry_count += 1
                wait_time = min(2 ** retry_count, 30)  # 指数退避，最大30秒
                logging.warning(f"API限流，等待{wait_time}秒后重试 (尝试 {retry_count}/{max_retries})")
                await asyncio.sleep(wait_time)
                continue
            else:
                logging.error(f"查询市场索引失败: {e}")
                raise

    logging.error(f"查询市场索引失败，已重试{max_retries}次")
    raise Exception(f"API限流严重，无法查询市场 {market_name}")


async def get_orderbook_price_at_depth(
        api_client: lighter.ApiClient,
        market_index: int,
        depth: int,
        is_bid: bool = True
) -> Optional[str]:
    """
    获取订单簿指定档位的价格
    
    Args:
        api_client: lighter API客户端
        market_index: 市场索引
        depth: 档位（1表示第一档，2表示第二档，以此类推）
        is_bid: True表示买盘价格，False表示卖盘价格
    
    Returns:
        价格字符串，如果档位不存在则返回None
    """
    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            order_api = lighter.OrderApi(api_client)
            # 获取订单簿数据，limit设置为depth以确保有足够的档位
            order_book_orders = await order_api.order_book_orders(market_index, limit=max(depth, 10))

            # 选择买盘或卖盘
            orders = order_book_orders.bids if is_bid else order_book_orders.asks

            # 检查是否有足够的档位
            if len(orders) < depth:
                logging.error(f"订单簿档位不足，需要第{depth}档，但只有{len(orders)}档")
                return None

            # 获取指定档位的价格（索引从0开始，所以减1）
            price = orders[depth - 1].price
            logging.info(f"市场{market_index} {'买' if is_bid else '卖'}{depth}档价格: {price}")
            return price

        except Exception as e:
            if "429" in str(e) or "Too Many Requests" in str(e):
                retry_count += 1
                wait_time = min(2 ** retry_count, 10)  # 指数退避，最大10秒
                logging.warning(f"获取订单簿API限流，等待{wait_time}秒后重试 (尝试 {retry_count}/{max_retries})")
                await asyncio.sleep(wait_time)
                continue
            else:
                logging.error(f"获取订单簿价格失败: {e}")
                raise

    logging.error(f"获取订单簿价格失败，已重试{max_retries}次")
    raise Exception(f"API限流严重，无法获取市场{market_index}的订单簿价格")


async def cancel_all_orders(
        signer_client: lighter.SignerClient,
        account_index: int,
        market_index: int
):
    """
    取消指定账户在指定市场的所有活跃订单
    
    Args:
        signer_client: lighter签名客户端
        account_index: 账户索引
        market_index: 市场索引
    """
    try:
        # 生成认证token（增加重试机制）
        auth_token = None
        for auth_retry in range(3):
            auth_token, auth_error = signer_client.create_auth_token_with_expiry()
            if auth_error is None:
                break
            logging.warning(f"生成认证token失败 (尝试 {auth_retry + 1}/3): {auth_error}")
            await asyncio.sleep(0.5)

        if auth_token is None:
            logging.warning("无法生成认证token，跳过清理历史订单")
            return

        order_api = lighter.OrderApi(signer_client.api_client)

        # 获取所有活跃订单
        try:
            orders = await order_api.account_active_orders(
                account_index=account_index,
                market_id=market_index,
                auth=auth_token
            )
        except Exception as e:
            # 如果查询失败（比如认证问题），记录警告但不中断程序
            logging.warning(f"查询活跃订单失败: {e}，跳过清理历史订单")
            return

        if not orders.orders or len(orders.orders) == 0:
            logging.info(f"账户{account_index}在市场{market_index}没有活跃订单")
            return

        logging.info(f"发现{len(orders.orders)}个活跃订单，准备取消")

        # 逐个取消订单
        for order in orders.orders:
            try:
                await signer_client.cancel_order(
                    market_index=market_index,
                    order_index=order.order_index
                )
                logging.info(f"已取消订单: {order.order_id}")
            except Exception as e:
                logging.error(f"取消订单{order.order_id}失败: {e}")

    except Exception as e:
        logging.warning(f"取消所有订单过程出错: {e}，继续执行")
        # 不再抛出异常，允许程序继续


async def get_account_active_orders(
        signer_client: lighter.SignerClient,
        account_index: int,
        market_index: int
):
    """
    取消指定账户在指定市场的所有活跃订单

    Args:
        signer_client: lighter签名客户端
        account_index: 账户索引
        market_index: 市场索引
    """
    try:
        # 生成认证token（增加重试机制）
        auth_token = None
        for auth_retry in range(3):
            auth_token, auth_error = signer_client.create_auth_token_with_expiry()
            if auth_error is None:
                break
            logging.warning(f"生成认证token失败 (尝试 {auth_retry + 1}/3): {auth_error}")
            await asyncio.sleep(0.5)

        if auth_token is None:
            logging.warning("无法生成认证token，跳过清理历史订单")
            return

        order_api = lighter.OrderApi(signer_client.api_client)

        # 获取所有活跃订单
        try:
            orders = await order_api.account_active_orders(
                account_index=account_index,
                market_id=market_index,
                auth=auth_token
            )
        except Exception as e:
            # 如果查询失败（比如认证问题），记录警告但不中断程序
            logging.warning(f"查询活跃订单失败: {e}，跳过清理历史订单")
            return

        if not orders.orders or len(orders.orders) == 0:
            logging.info(f"账户{account_index}在市场{market_index}没有活跃订单")
            return

        logging.info(f"发现{len(orders.orders)}个活跃订单，准备取消")

        return orders.orders

    except Exception as e:
        logging.warning(f"取消所有订单过程出错: {e}，继续执行")
        # 不再抛出异常，允许程序继续


async def get_positions(
        api_client: lighter.ApiClient,
        account_index: int,
        market_index: int
):
    """
    获取持仓

    Args:
        signer_client: lighter签名客户端
        account_index: 账户索引
        market_index: 市场索引
    """
    try:
        """Get positions using official SDK."""
        # Use shared API client
        account_api = lighter.AccountApi(api_client)

        # Get account info
        account_data = await account_api.account(by="index", value=str(account_index))

        if not account_data or not account_data.accounts:
            logging.log("Failed to get positions")
            raise ValueError("Failed to get positions")

        logging.log(f"Failed to get positions{account_data}")

        for position in account_data.accounts[0].positions:
            if position.market_id == market_index:
                return Decimal(position.position)

        return Decimal(0)

    except Exception as e:
        logging.warning(f"获取持仓过程出错: {e}，继续执行")
        # 不再抛出异常，允许程序继续


def parse_price_to_int(price_str: str) -> int:
    """
    将价格字符串转换为整数格式（去除小数点）
    
    Args:
        price_str: 价格字符串，如 "3024.66"
    
    Returns:
        整数价格，如 302466
    """
    return int(price_str.replace(".", ""))


def calculate_avg_price(filled_base_amount: str, filled_quote_amount: str) -> str:
    """
    计算平均成交价格
    
    Args:
        filled_base_amount: 成交的基础资产数量
        filled_quote_amount: 成交的计价资产数量
    
    Returns:
        平均价格字符串
    """
    try:
        base = float(filled_base_amount)
        quote = float(filled_quote_amount)
        if base == 0:
            return "0"
        avg_price = quote / base
        return f"{avg_price:.2f}"
    except Exception as e:
        logging.error(f"计算平均价格失败: {e}")
        return "0"


def load_config(config_path: str) -> Dict[str, Any]:
    """
    加载YAML配置文件
    
    Args:
        config_path: 配置文件路径
    
    Returns:
        配置字典
    """
    import yaml

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        logging.info(f"配置文件加载成功: {config_path}")
        return config
    except Exception as e:
        logging.error(f"加载配置文件失败: {e}")
        raise
