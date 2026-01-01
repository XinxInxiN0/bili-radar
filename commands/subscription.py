"""订阅管理指令

实现 /radar add/del/list/on/off 等订阅相关指令
"""

import re
from typing import Tuple
import logging

from peewee import IntegrityError

logger = logging.getLogger(__name__)


class RadarAddCommand:
    """添加订阅指令：/radar add <mid>"""
    
    command_pattern = re.compile(r"^/radar\s+add\s+(\d+)$")
    
    def __init__(self, dao, bili_client, config):
        """初始化指令
        
        Args:
            dao: BiliSubscriptionDAO 实例
            bili_client: BiliClient 实例
            config: 插件配置对象
        """
        self.dao = dao
        self.bili_client = bili_client
        self.config = config
    
    async def can_execute(self, message: str, user_id: str, is_admin: bool) -> bool:
        """检查是否匹配该指令"""
        return bool(self.command_pattern.match(message.strip()))
    
    async def execute(
        self,
        message: str,
        stream_id: str,
        user_id: str,
        is_admin: bool,
    ) -> Tuple[bool, str, bool]:
        """执行指令
        
        Returns:
            (成功, 回复消息, 是否拦截后续处理)
        """
        # 权限检查
        if not self._check_permission(user_id, is_admin):
            return False, "❌ 权限不足：仅管理员或白名单用户可执行此操作", True
        
        # 解析参数
        match = self.command_pattern.match(message.strip())
        if not match:
            return False, "❌ 指令格式错误", True
        
        mid = int(match.group(1))
        
        try:
            # 检查是否已订阅
            existing = await self.dao.get_subscription(stream_id, mid)
            if existing:
                return (
                    False,
                    f"⚠️ 已订阅 UP 主 {mid}，无需重复添加",
                    True,
                )
            
            # 获取最新视频（作为初始基准）
            logger.info(f"Fetching latest video for mid={mid} to initialize subscription")
            latest_video = await self.bili_client.fetch_latest_video(mid)
            
            if latest_video:
                # 创建订阅并初始化 last_* 字段
                await self.dao.add_subscription(
                    stream_id=stream_id,
                    mid=mid,
                    last_bvid=latest_video.bvid,
                    last_created_ts=latest_video.created_ts,
                )
                logger.info(
                    f"Subscription added: stream_id={stream_id}, mid={mid}, "
                    f"initialized with bvid={latest_video.bvid}"
                )
                return (
                    True,
                    f"✅ 成功订阅 UP 主 {mid}\n"
                    f"当前最新视频：{latest_video.title}\n"
                    f"后续将自动推送新视频",
                    True,
                )
            else:
                # 获取失败，仍然创建订阅但不初始化
                await self.dao.add_subscription(
                    stream_id=stream_id,
                    mid=mid,
                )
                logger.warning(
                    f"Failed to fetch latest video for mid={mid}, "
                    f"subscription created without initialization"
                )
                return (
                    True,
                    f"⚠️ 已订阅 UP 主 {mid}，但无法获取最新视频信息\n"
                    f"可能原因：UP 无投稿、API 限流或 mid 无效",
                    True,
                )
        
        except IntegrityError:
            # 唯一索引冲突（理论上前面已检查，但保险起见）
            return False, f"⚠️ 已订阅 UP 主 {mid}", True
        
        except Exception as e:
            logger.error(f"Failed to add subscription: {e}", exc_info=True)
            return False, f"❌ 添加订阅失败：{str(e)}", True
    
    def _check_permission(self, user_id: str, is_admin: bool) -> bool:
        """检查权限"""
        admin_only = getattr(self.config.permission, "admin_only", True)
        allowlist = getattr(self.config.permission, "operator_allowlist", [])
        
        if admin_only:
            return is_admin or user_id in allowlist
        return True


class RadarDelCommand:
    """删除订阅指令：/radar del <mid>"""
    
    command_pattern = re.compile(r"^/radar\s+del\s+(\d+)$")
    
    def __init__(self, dao, config):
        self.dao = dao
        self.config = config
    
    async def can_execute(self, message: str, user_id: str, is_admin: bool) -> bool:
        return bool(self.command_pattern.match(message.strip()))
    
    async def execute(
        self,
        message: str,
        stream_id: str,
        user_id: str,
        is_admin: bool,
    ) -> Tuple[bool, str, bool]:
        # 权限检查
        if not self._check_permission(user_id, is_admin):
            return False, "❌ 权限不足：仅管理员或白名单用户可执行此操作", True
        
        match = self.command_pattern.match(message.strip())
        if not match:
            return False, "❌ 指令格式错误", True
        
        mid = int(match.group(1))
        
        try:
            success = await self.dao.remove_subscription(stream_id, mid)
            if success:
                logger.info(f"Subscription removed: stream_id={stream_id}, mid={mid}")
                return True, f"✅ 已删除 UP 主 {mid} 的订阅", True
            else:
                return False, f"⚠️ 未订阅 UP 主 {mid}，无需删除", True
        
        except Exception as e:
            logger.error(f"Failed to remove subscription: {e}", exc_info=True)
            return False, f"❌ 删除订阅失败：{str(e)}", True
    
    def _check_permission(self, user_id: str, is_admin: bool) -> bool:
        admin_only = getattr(self.config.permission, "admin_only", True)
        allowlist = getattr(self.config.permission, "operator_allowlist", [])
        if admin_only:
            return is_admin or user_id in allowlist
        return True


class RadarListCommand:
    """列出订阅指令：/radar list"""
    
    command_pattern = re.compile(r"^/radar\s+list$")
    
    def __init__(self, dao):
        self.dao = dao
    
    async def can_execute(self, message: str, user_id: str, is_admin: bool) -> bool:
        return bool(self.command_pattern.match(message.strip()))
    
    async def execute(
        self,
        message: str,
        stream_id: str,
        user_id: str,
        is_admin: bool,
    ) -> Tuple[bool, str, bool]:
        try:
            subscriptions = await self.dao.get_subscriptions_by_stream(stream_id)
            
            if not subscriptions:
                return True, "📭 本群暂无订阅", True
            
            # 构造列表
            lines = ["📋 本群订阅列表：\n"]
            for i, sub in enumerate(subscriptions, 1):
                status = "✅" if sub.enabled else "🔕"
                last_info = (
                    f"最新：{sub.last_bvid}" if sub.last_bvid
                    else "暂无记录"
                )
                lines.append(
                    f"{i}. {status} UP {sub.mid}\n"
                    f"   {last_info}"
                )
            
            return True, "\n".join(lines), True
        
        except Exception as e:
            logger.error(f"Failed to list subscriptions: {e}", exc_info=True)
            return False, f"❌ 获取订阅列表失败：{str(e)}", True


class RadarOnCommand:
    """启用推送指令：/radar on <mid>"""
    
    command_pattern = re.compile(r"^/radar\s+on\s+(\d+)$")
    
    def __init__(self, dao, config):
        self.dao = dao
        self.config = config
    
    async def can_execute(self, message: str, user_id: str, is_admin: bool) -> bool:
        return bool(self.command_pattern.match(message.strip()))
    
    async def execute(
        self,
        message: str,
        stream_id: str,
        user_id: str,
        is_admin: bool,
    ) -> Tuple[bool, str, bool]:
        if not self._check_permission(user_id, is_admin):
            return False, "❌ 权限不足：仅管理员或白名单用户可执行此操作", True
        
        match = self.command_pattern.match(message.strip())
        if not match:
            return False, "❌ 指令格式错误", True
        
        mid = int(match.group(1))
        
        try:
            success = await self.dao.toggle_enabled(stream_id, mid, enabled=True)
            if success:
                logger.info(f"Subscription enabled: stream_id={stream_id}, mid={mid}")
                return True, f"✅ 已启用 UP 主 {mid} 的推送", True
            else:
                return False, f"⚠️ 未订阅 UP 主 {mid}", True
        
        except Exception as e:
            logger.error(f"Failed to enable subscription: {e}", exc_info=True)
            return False, f"❌ 启用推送失败：{str(e)}", True
    
    def _check_permission(self, user_id: str, is_admin: bool) -> bool:
        admin_only = getattr(self.config.permission, "admin_only", True)
        allowlist = getattr(self.config.permission, "operator_allowlist", [])
        if admin_only:
            return is_admin or user_id in allowlist
        return True


class RadarOffCommand:
    """禁用推送指令：/radar off <mid>"""
    
    command_pattern = re.compile(r"^/radar\s+off\s+(\d+)$")
    
    def __init__(self, dao, config):
        self.dao = dao
        self.config = config
    
    async def can_execute(self, message: str, user_id: str, is_admin: bool) -> bool:
        return bool(self.command_pattern.match(message.strip()))
    
    async def execute(
        self,
        message: str,
        stream_id: str,
        user_id: str,
        is_admin: bool,
    ) -> Tuple[bool, str, bool]:
        if not self._check_permission(user_id, is_admin):
            return False, "❌ 权限不足：仅管理员或白名单用户可执行此操作", True
        
        match = self.command_pattern.match(message.strip())
        if not match:
            return False, "❌ 指令格式错误", True
        
        mid = int(match.group(1))
        
        try:
            success = await self.dao.toggle_enabled(stream_id, mid, enabled=False)
            if success:
                logger.info(f"Subscription disabled: stream_id={stream_id}, mid={mid}")
                return True, f"🔕 已禁用 UP 主 {mid} 的推送（订阅保留）", True
            else:
                return False, f"⚠️ 未订阅 UP 主 {mid}", True
        
        except Exception as e:
            logger.error(f"Failed to disable subscription: {e}", exc_info=True)
            return False, f"❌ 禁用推送失败：{str(e)}", True
    
    def _check_permission(self, user_id: str, is_admin: bool) -> bool:
        admin_only = getattr(self.config.permission, "admin_only", True)
        allowlist = getattr(self.config.permission, "operator_allowlist", [])
        if admin_only:
            return is_admin or user_id in allowlist
        return True
