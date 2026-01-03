"""工具指令

实现 /radar test 和 /radar help 指令
"""

import re
from typing import Tuple
import logging

logger = logging.getLogger(__name__)


class RadarTestCommand:
    """测试推送指令：/radar test <mid>
    
    立即抓取最新视频并推送，用于排障
    """
    
    command_pattern = re.compile(r"^/radar\s+test\s+(\d+)$")
    
    def __init__(self, dao, bili_client, message_sender, config):
        """初始化指令
        
        Args:
            dao: BiliSubscriptionDAO 实例
            bili_client: BiliClient 实例
            message_sender: 消息发送器（send_api）
            config: 插件配置对象
        """
        self.dao = dao
        self.bili_client = bili_client
        self.message_sender = message_sender
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
            # 抓取最新视频
            logger.info(f"Test command: fetching latest video for mid={mid}")
            latest_video = await self.bili_client.fetch_latest_video(mid)
            
            if not latest_video:
                return (
                    False,
                    f"⚠️ 无法获取 UP 主 {mid} 的最新视频\n"
                    f"可能原因：UP 无投稿、API 限流或 mid 无效",
                    True,
                )
            
            # 生成推送消息
            template = getattr(self.config.push, "message_template", "{title}\n{url}")
            push_message = template.format(
                title=latest_video.title,
                author=latest_video.author,
                bvid=latest_video.bvid,
                url=latest_video.url,
            )
            
            # 发送消息
            await self.message_sender.text_to_stream(push_message, stream_id)
            
            logger.info(f"Test push successful: mid={mid}, bvid={latest_video.bvid}")
            
            return (
                True,
                f"✅ 测试推送成功\n"
                f"UP 主：{mid}\n"
                f"视频：{latest_video.title}",
                True,
            )
        
        except Exception as e:
            logger.error(f"Failed to test push for mid={mid}: {e}", exc_info=True)
            return False, f"❌ 测试推送失败：{str(e)}", True
    
    def _check_permission(self, user_id: str, is_admin: bool) -> bool:
        admin_only = getattr(self.config.permission, "admin_only", True)
        allowlist = getattr(self.config.permission, "operator_allowlist", [])
        if admin_only:
            return is_admin or user_id in allowlist
        return True


class RadarHelpCommand:
    """帮助指令：/radar help"""
    
    command_pattern = re.compile(r"^/radar\s+help$")
    
    async def can_execute(self, message: str, user_id: str, is_admin: bool) -> bool:
        return bool(self.command_pattern.match(message.strip()))
    
    async def execute(
        self,
        message: str,
        stream_id: str,
        user_id: str,
        is_admin: bool,
    ) -> Tuple[bool, str, bool]:
        help_text = """📖 麦哔雷达 - Bilibili UP 主新视频推送

【订阅管理】
/radar add <mid>    添加订阅
/radar del <mid>    删除订阅
/radar list         查看本群订阅
/radar on <mid>     启用推送
/radar off <mid>    禁用推送（保留订阅）

【工具指令】
/radar test <mid>   测试推送最新视频
/radar help         显示此帮助

【说明】
• mid 为 UP 主 ID，可从主页 URL 获取
  例如：space.bilibili.com/546195 中的 546195
• 添加订阅后仅推送后续新视频，不推送历史
• 推送消息可在配置中自定义模板

【示例】
/radar add 546195   订阅 UP 主 546195
/radar list         查看本群所有订阅
"""
        return True, help_text, True
