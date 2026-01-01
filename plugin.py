"""麦哔雷达 - Bilibili UP 主新视频推送插件

跟踪指定 B 站 UP 的新投稿视频，并将最新视频链接推送到订阅群
支持群内 /radar 指令管理订阅
"""

from __future__ import annotations

import asyncio
import re
from typing import List, Tuple, Type, Optional

# MaiBot 插件系统导入
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseCommand,
    BaseEventHandler,
    ComponentInfo,
    ConfigField,
    EventType,
    MaiMessages,
    CustomEventHandlerResult,
)
from src.plugin_system.apis import send_api
from src.common.logger import get_logger

# 插件模块导入
from .models import BiliSubscriptionDAO
from .bili import BiliClient, WbiSigner
from .tasks import BiliPollingTask

logger = get_logger(__name__)

# 插件元信息
__plugin_version__ = "1.0.0"

# 模块级全局变量，用于 Command 访问插件实例
_plugin_instance = None


def get_plugin_instance():
    """获取插件实例"""
    return _plugin_instance


# ===== Command 组件 =====


class RadarAddCommand(BaseCommand):
    """添加订阅指令：/radar add <mid>"""
    
    command_name = "radar_add"
    command_description = "添加 Bilibili UP 主订阅"
    command_pattern = r"^/radar\s+add\s+(\d+)$"
    
    async def execute(self) -> Tuple[bool, str, int]:
        """执行添加订阅"""
        try:
            # 解析 mid
            match = re.match(self.command_pattern, self.message.raw_message.strip())
            if not match:
                await self.send_text("❌ 指令格式错误", storage_message=False)
                return True, None, 2
            
            mid = int(match.group(1))
            stream_id = self.message.chat_stream.stream_id if self.message.chat_stream else ""
            
            # 获取插件配置和组件
            plugin = get_plugin_instance()
            if not plugin:
                await self.send_text("❌ 插件未正确初始化", storage_message=False)
                return True, None, 2
            
            await plugin.ensure_initialized()
            dao = plugin.dao
            bili_client = plugin.bili_client
            
            if not dao or not bili_client:
                await self.send_text("❌ 插件组件未就绪（数据库或 API 客户端未初始化）", storage_message=False)
                return True, None, 2
            
            # 检查权限
            if not self._check_permission():
                await self.send_text("❌ 权限不足：仅管理员或白名单用户可执行此操作", storage_message=False)
                return True, None, 2
            
            # 检查是否已订阅
            existing = await dao.get_subscription(stream_id, mid)
            if existing:
                await self.send_text(f"⚠️ 已订阅 UP 主 {mid}，无需重复添加", storage_message=False)
                return True, None, 2
            
            # 获取最新视频（作为初始基准）
            logger.info(f"Fetching latest video for mid={mid} to initialize subscription")
            latest_video = await bili_client.fetch_latest_video(mid)
            
            if latest_video:
                # 创建订阅并初始化 last_* 字段
                await dao.add_subscription(
                    stream_id=stream_id,
                    mid=mid,
                    last_bvid=latest_video.bvid,
                    last_created_ts=latest_video.created_ts,
                )
                logger.info(
                    f"Subscription added: stream_id={stream_id}, mid={mid}, "
                    f"initialized with bvid={latest_video.bvid}"
                )
                response_msg = (
                    f"✅ 成功订阅 UP 主 {mid}\n"
                    f"当前最新视频：{latest_video.title}\n"
                    f"后续将自动推送新视频"
                )
                await self.send_text(response_msg, storage_message=False)
                return (True, None, 2)
            else:
                # 获取失败，仍然创建订阅但不初始化
                await dao.add_subscription(stream_id=stream_id, mid=mid)
                logger.warning(
                    f"Failed to fetch latest video for mid={mid}, "
                    f"subscription created without initialization"
                )
                response_msg = (
                    f"⚠️ 已订阅 UP 主 {mid}，但无法获取最新视频信息\n"
                    f"可能原因：UP 无投稿、API 限流或 mid 无效"
                )
                await self.send_text(response_msg, storage_message=False)
                return (True, None, 2)
        
        except Exception as e:
            logger.error(f"Failed to add subscription: {e}", exc_info=True)
            await self.send_text(f"❌ 添加订阅失败：{str(e)}", storage_message=False)
            return True, None, 2
    
    def _check_permission(self) -> bool:
        """检查用户权限"""
        admin_only = self.get_config("permission.admin_only", True)
        allowlist = self.get_config("permission.operator_allowlist", [])
        
        if admin_only:
            # TODO: 检查用户是否为管理员（需要 MaiBot API 支持）
            # 暂时允许所有人操作
            return True
        return True


class RadarDelCommand(BaseCommand):
    """删除订阅指令：/radar del <mid>"""
    
    command_name = "radar_del"
    command_description = "删除 Bilibili UP 主订阅"
    command_pattern = r"^/radar\s+del\s+(\d+)$"
    
    async def execute(self) -> Tuple[bool, str, int]:
        try:
            match = re.match(self.command_pattern, self.message.raw_message.strip())
            if not match:
                await self.send_text("❌ 指令格式错误", storage_message=False)
                return True, None, 2
            
            mid = int(match.group(1))
            stream_id = self.message.chat_stream.stream_id if self.message.chat_stream else ""
            
            plugin = get_plugin_instance()
            if not plugin:
                await self.send_text("❌ 插件未初始化或未启用", storage_message=False)
                return True, None, 2
            
            await plugin.ensure_initialized()
            dao = plugin.dao
            if not dao:
                await self.send_text("❌ 数据库未初始化", storage_message=False)
                return True, None, 2
            
            success = await dao.remove_subscription(stream_id, mid)
            if success:
                logger.info(f"Subscription removed: stream_id={stream_id}, mid={mid}")
                response_msg = f"✅ 已删除 UP 主 {mid} 的订阅"
                await self.send_text(response_msg, storage_message=False)
                return True, None, 2
            else:
                response_msg = f"⚠️ 未订阅 UP 主 {mid}，无需删除"
                await self.send_text(response_msg, storage_message=False)
                return True, None, 2
        
        except Exception as e:
            logger.error(f"Failed to remove subscription: {e}", exc_info=True)
            await self.send_text(f"❌ 删除订阅失败：{str(e)}", storage_message=False)
            return True, None, 2


class RadarListCommand(BaseCommand):
    """列出订阅指令：/radar list"""
    
    command_name = "radar_list"
    command_description = "列出本群所有 Bilibili UP 主订阅"
    command_pattern = r"^/radar\s+list$"
    
    async def execute(self) -> Tuple[bool, str, int]:
        try:
            stream_id = self.message.chat_stream.stream_id if self.message.chat_stream else ""
            
            plugin = get_plugin_instance()
            if not plugin:
                await self.send_text("❌ 插件未初始化或未启用", storage_message=False)
                return True, None, 2
            
            await plugin.ensure_initialized()
            dao = plugin.dao
            if not dao:
                await self.send_text("❌ 数据库未初始化", storage_message=False)
                return True, None, 2
            
            subscriptions = await dao.get_subscriptions_by_stream(stream_id)
            
            if not subscriptions:
                response_msg = "📭 本群暂无订阅"
                await self.send_text(response_msg, storage_message=False)
                return True, None, 2
            
            # 构造列表
            lines = ["📋 本群订阅列表：\n"]
            for i, sub in enumerate(subscriptions, 1):
                status = "✅" if sub.enabled else "🔕"
                last_info = f"最新：{sub.last_bvid}" if sub.last_bvid else "暂无记录"
                lines.append(f"{i}. {status} UP {sub.mid}\n   {last_info}")
            
            response_msg = "\n".join(lines)
            await self.send_text(response_msg, storage_message=False)
            return True, None, 2
        
        except Exception as e:
            logger.error(f"Failed to list subscriptions: {e}", exc_info=True)
            await self.send_text(f"❌ 获取订阅列表失败：{str(e)}", storage_message=False)
            return True, None, 2


class RadarOnCommand(BaseCommand):
    """启用推送指令：/radar on <mid>"""
    
    command_name = "radar_on"
    command_description = "启用 UP 主推送"
    command_pattern = r"^/radar\s+on\s+(\d+)$"
    
    async def execute(self) -> Tuple[bool, str, int]:
        try:
            match = re.match(self.command_pattern, self.message.raw_message.strip())
            if not match:
                await self.send_text("❌ 指令格式错误", storage_message=False)
                return True, None, 2
            
            mid = int(match.group(1))
            stream_id = self.message.chat_stream.stream_id if self.message.chat_stream else ""
            
            plugin = get_plugin_instance()
            if not plugin:
                await self.send_text("❌ 插件未初始化或未启用", storage_message=False)
                return True, None, 2
            
            await plugin.ensure_initialized()
            dao = plugin.dao
            if not dao:
                await self.send_text("❌ 数据库未初始化", storage_message=False)
                return True, None, 2
            
            success = await dao.toggle_enabled(stream_id, mid, enabled=True)
            if success:
                logger.info(f"Subscription enabled: stream_id={stream_id}, mid={mid}")
                response_msg = f"✅ 已启用 UP 主 {mid} 的推送"
                await self.send_text(response_msg, storage_message=False)
                return True, None, 2
            else:
                response_msg = f"⚠️ 未订阅 UP 主 {mid}"
                await self.send_text(response_msg, storage_message=False)
                return True, None, 2
        
        except Exception as e:
            logger.error(f"Failed to enable subscription: {e}", exc_info=True)
            await self.send_text(f"❌ 启用推送失败：{str(e)}", storage_message=False)
            return True, None, 2


class RadarOffCommand(BaseCommand):
    """禁用推送指令：/radar off <mid>"""
    
    command_name = "radar_off"
    command_description = "禁用 UP 主推送（保留订阅）"
    command_pattern = r"^/radar\s+off\s+(\d+)$"
    
    async def execute(self) -> Tuple[bool, str, int]:
        try:
            match = re.match(self.command_pattern, self.message.raw_message.strip())
            if not match:
                await self.send_text("❌ 指令格式错误", storage_message=False)
                return True, None, 2
            
            mid = int(match.group(1))
            stream_id = self.message.chat_stream.stream_id if self.message.chat_stream else ""
            
            plugin = get_plugin_instance()
            if not plugin:
                await self.send_text("❌ 插件未初始化或未启用", storage_message=False)
                return True, None, 2
            
            await plugin.ensure_initialized()
            dao = plugin.dao
            if not dao:
                await self.send_text("❌ 数据库未初始化", storage_message=False)
                return True, None, 2
            
            success = await dao.toggle_enabled(stream_id, mid, enabled=False)
            if success:
                logger.info(f"Subscription disabled: stream_id={stream_id}, mid={mid}")
                response_msg = f"🔕 已禁用 UP 主 {mid} 的推送（订阅保留）"
                await self.send_text(response_msg, storage_message=False)
                return True, None, 2
            else:
                response_msg = f"⚠️ 未订阅 UP 主 {mid}"
                await self.send_text(response_msg, storage_message=False)
                return True, None, 2
        
        except Exception as e:
            logger.error(f"Failed to disable subscription: {e}", exc_info=True)
            await self.send_text(f"❌ 禁用推送失败：{str(e)}", storage_message=False)
            return True, None, 2


class RadarTestCommand(BaseCommand):
    """测试推送指令：/radar test <mid>"""
    
    command_name = "radar_test"
    command_description = "测试推送最新视频"
    command_pattern = r"^/radar\s+test\s+(\d+)$"
    
    async def execute(self) -> Tuple[bool, str, int]:
        try:
            match = re.match(self.command_pattern, self.message.raw_message.strip())
            if not match:
                await self.send_text("❌ 指令格式错误", storage_message=False)
                return True, None, 2
            
            mid = int(match.group(1))
            stream_id = self.message.chat_stream.stream_id if self.message.chat_stream else ""
            
            plugin = get_plugin_instance()
            if not plugin:
                await self.send_text("❌ 插件未初始化或未启用", storage_message=False)
                return True, None, 2
            
            await plugin.ensure_initialized()
            bili_client = plugin.bili_client
            if not bili_client:
                await self.send_text("❌ Bilibili 客户端未初始化", storage_message=False)
                return True, None, 2
            
            # 抓取最新视频
            logger.info(f"Test command: fetching latest video for mid={mid}")
            latest_video = await bili_client.fetch_latest_video(mid)
            
            if not latest_video:
                await self.send_text(
                    f"⚠️ 无法获取 UP 主 {mid} 的最新视频\n"
                    f"可能原因：UP 无投稿、API 限流或 mid 无效",
                    storage_message=False
                )
                return True, None, 2
            
            # 生成推送消息
            template = self.get_config(
                "push.message_template",
                "🎬 新视频推送\n标题：{title}\n作者：{author}\n链接：{url}",
            )
            push_message = template.format(
                title=latest_video.title,
                author=latest_video.author,
                bvid=latest_video.bvid,
                url=latest_video.url,
            )
            
            # 发送消息（使用 send_text 方法）
            await self.send_text(push_message, storage_message=False)
            
            logger.info(f"Test push successful: mid={mid}, bvid={latest_video.bvid}")
            
            await self.send_text(
                f"✅ 测试推送成功\nUP 主：{mid}\n视频：{latest_video.title}",
                storage_message=False
            )
            return True, None, 2
        
        except Exception as e:
            logger.error(f"Failed to test push for mid={mid}: {e}", exc_info=True)
            await self.send_text(f"❌ 测试推送失败：{str(e)}", storage_message=False)
            return True, None, 2


class RadarHelpCommand(BaseCommand):
    """帮助指令：/radar help"""
    
    command_name = "radar_help"
    command_description = "显示麦哔雷达帮助信息"
    command_pattern = r"^/radar\s+help$"
    
    async def execute(self) -> Tuple[bool, str, int]:
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
        await self.send_text(help_text, storage_message=False)
        return True, None, 2


class BiliRadarInitHandler(BaseEventHandler):
    """插件启动初始化处理器"""
    
    event_type = EventType.ON_START
    handler_name = "bili_radar_init"
    handler_description = "初始化 Bilibili 雷达插件组件"
    
    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, Optional[str], Optional[CustomEventHandlerResult], Optional[MaiMessages]]:
        plugin = get_plugin_instance()
        if plugin:
            await plugin.ensure_initialized()
            logger.info("插件已通过 ON_START 事件初始化")
        return True, True, None, None, None


# ===== 插件主类 =====


@register_plugin
class BiliRadarPlugin(BasePlugin):
    """麦哔雷达插件主类"""
    
    # 插件基本信息
    plugin_name: str = "maibot_bili_radar"
    enable_plugin: bool = False
    dependencies: List[str] = []
    python_dependencies: List[str] = ["httpx", "peewee"]
    config_file_name: str = "config.toml"
    
    # 配置节描述
    config_section_descriptions = {
        "plugin": "插件基本信息",
        "polling": "轮询配置",
        "bilibili": "Bilibili API 配置",
        "push": "推送配置",
        "permission": "权限配置",
    }
    
    # 配置 Schema 定义
    config_schema: dict = {
        "plugin": {
            "config_version": ConfigField(type=str, default="1.0.0", description="配置文件版本"),
            "enabled": ConfigField(type=bool, default=False, description="是否启用插件"),
        },
        "polling": {
            "interval_seconds": ConfigField(type=int, default=120, description="轮询间隔（秒）"),
            "max_concurrency": ConfigField(type=int, default=3, description="同时请求的最大 mid 数量"),
        },
        "bilibili": {
            "timeout_seconds": ConfigField(type=int, default=10, description="API 请求超时时间（秒）"),
            "user_agent": ConfigField(
                type=str,
                default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                description="User-Agent 请求头",
            ),
            "referer": ConfigField(type=str, default="https://www.bilibili.com", description="Referer 请求头"),
            "cookie_sessdata": ConfigField(type=str, default="", description="可选：SESSDATA cookie（增强稳定性）"),
            "cookie_buvid3": ConfigField(type=str, default="", description="可选：buvid3 cookie"),
            "wbi_keys_refresh_hours": ConfigField(type=int, default=12, description="WBI 密钥缓存刷新周期（小时）"),
        },
        "push": {
            "message_template": ConfigField(
                type=str,
                default="🎬 新视频推送\n标题：{title}\n作者：{author}\n链接：{url}",
                description="推送消息模板（支持 {title}, {author}, {bvid}, {url}）",
            ),
        },
        "permission": {
            "admin_only": ConfigField(type=bool, default=True, description="是否仅管理员可修改订阅"),
            "operator_allowlist": ConfigField(type=list, default=[], description="操作员白名单（用户 ID 列表）"),
        },
    }
    
    def __init__(self, *args, **kwargs):
        """初始化插件"""
        super().__init__(*args, **kwargs)
        
        # 设置全局实例
        global _plugin_instance
        _plugin_instance = self
        
        # 组件初始化状态
        self.dao: Optional[BiliSubscriptionDAO] = None
        self.wbi_signer: Optional[WbiSigner] = None
        self.bili_client: Optional[BiliClient] = None
        self.polling_task: Optional[BiliPollingTask] = None
        self._init_done = False
        self._init_lock = asyncio.Lock()
        
        logger.info(f"麦哔雷达 v{__plugin_version__} 已实例化")

    async def ensure_initialized(self) -> None:
        """确保组件已初始化（异步惰性初始化）"""
        if self._init_done:
            return
            
        async with self._init_lock:
            if self._init_done:
                return
                
            try:
                from src.common.database.database import db
                
                # 1. 初始化数据库
                await BiliSubscriptionDAO.create_table_if_not_exists(db)
                self.dao = BiliSubscriptionDAO
                
                # 2. 初始化 WBI 签名器
                user_agent = self.get_config(
                    "bilibili.user_agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                )
                referer = self.get_config("bilibili.referer", "https://www.bilibili.com")
                self.wbi_signer = WbiSigner(
                    headers={
                        "User-Agent": user_agent,
                        "Referer": referer,
                    }
                )
                wbi_refresh_hours = self.get_config("bilibili.wbi_keys_refresh_hours", 12)
                self.wbi_signer.set_cache_duration(wbi_refresh_hours)
                
                # 3. 初始化 Bilibili 客户端
                self.bili_client = BiliClient(
                    wbi_signer=self.wbi_signer,
                    timeout=self.get_config("bilibili.timeout_seconds", 10),
                    user_agent=self.get_config(
                        "bilibili.user_agent",
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    ),
                    referer=self.get_config("bilibili.referer", "https://www.bilibili.com"),
                    cookie_sessdata=self.get_config("bilibili.cookie_sessdata", ""),
                    cookie_buvid3=self.get_config("bilibili.cookie_buvid3", ""),
                )
                
                # 4. 初始化轮询任务
                self.polling_task = BiliPollingTask(
                    dao=self.dao,
                    bili_client=self.bili_client,
                    send_api_module=send_api,
                    config=self,
                )
                await self.polling_task.start()
                
                self._init_done = True
                logger.info(f"{self.log_prefix} 核心组件初始化完成")
                
            except Exception as e:
                logger.error(f"{self.log_prefix} 初始化组件失败: {e}", exc_info=True)
                raise
    
    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """注册插件组件"""
        return [
            (RadarAddCommand.get_command_info(), RadarAddCommand),
            (RadarDelCommand.get_command_info(), RadarDelCommand),
            (RadarListCommand.get_command_info(), RadarListCommand),
            (RadarOnCommand.get_command_info(), RadarOnCommand),
            (RadarOffCommand.get_command_info(), RadarOffCommand),
            (RadarTestCommand.get_command_info(), RadarTestCommand),
            (RadarHelpCommand.get_command_info(), RadarHelpCommand),
            (BiliRadarInitHandler.get_handler_info(), BiliRadarInitHandler),
        ]
