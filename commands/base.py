"""指令基础工具

提供权限检查装饰器等通用功能
"""

from typing import Callable, Any
from functools import wraps
import logging

logger = logging.getLogger(__name__)


def requires_permission(config_getter: Callable[[], Any]):
    """权限检查装饰器
    
    根据配置检查用户是否有权限执行订阅操作
    
    Args:
        config_getter: 获取配置对象的函数
        
    Usage:
        @requires_permission(lambda: plugin.config)
        async def execute(self, ...):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            # 获取配置
            config = config_getter()
            
            # 获取用户信息（从 MaiBot 消息上下文）
            # 这里假设 self 有 message 属性
            user_id = getattr(self, "user_id", None)
            is_admin = getattr(self, "is_admin", False)
            
            # 检查权限
            admin_only = getattr(config.permission, "admin_only", True)
            allowlist = getattr(config.permission, "operator_allowlist", [])
            
            if admin_only:
                # 仅管理员或白名单用户可操作
                if not is_admin and user_id not in allowlist:
                    logger.warning(
                        f"User {user_id} attempted to execute {func.__name__} "
                        f"but lacks permission (admin_only=True)"
                    )
                    return (
                        False,
                        "❌ 权限不足：仅管理员或白名单用户可执行此操作",
                        True,
                    )
            
            # 权限检查通过，执行原函数
            return await func(self, *args, **kwargs)
        
        return wrapper
    return decorator
