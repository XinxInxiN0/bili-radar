"""麦哔雷达 - Bilibili UP 主新视频推送插件

跟踪指定 B 站 UP 的新投稿视频，并将最新视频链接推送到订阅群
支持群内 /radar 指令管理订阅
"""

import logging
from typing import Any, Dict

# MaiBot 插件系统导入（需要根据实际 MaiBot API 调整）
# from maibot.plugin import Plugin
# from maibot.config import ConfigSchema, ConfigField
# from maibot.database import get_database
# from maibot.message import MessageHandler
# from maibot.send_api import send_api

# 插件模块导入
from .models import BiliSubscriptionDAO
from .bili import BiliClient, WbiSigner
from .commands import (
    RadarAddCommand,
    RadarDelCommand,
    RadarListCommand,
    RadarOnCommand,
    RadarOffCommand,
    RadarTestCommand,
    RadarHelpCommand,
)
from .tasks import BiliPollingTask

logger = logging.getLogger(__name__)

# 插件元信息
__plugin_name__ = "麦哔雷达"
__plugin_version__ = "1.0.0"
__plugin_author__ = "XinxInxiN0"


class BiliRadarPlugin:
    """麦哔雷达插件主类
    
    负责插件初始化、配置加载、组件注册和生命周期管理
    """
    
    def __init__(self):
        """初始化插件"""
        self.config = None
        self.dao = None
        self.wbi_signer = None
        self.bili_client = None
        self.polling_task = None
        self.commands = []
        
        logger.info(f"{__plugin_name__} v{__plugin_version__} initializing...")
    
    async def on_load(self, plugin_context: Any) -> None:
        """插件加载时调用
        
        Args:
            plugin_context: MaiBot 插件上下文（包含 config, database, send_api 等）
        """
        try:
            # 1. 加载配置
            self.config = plugin_context.config
            logger.info("Configuration loaded")
            
            # 2. 初始化数据库
            database = plugin_context.database
            await BiliSubscriptionDAO.create_table_if_not_exists(database)
            self.dao = BiliSubscriptionDAO
            logger.info("Database initialized")
            
            # 3. 初始化 WBI 签名器
            self.wbi_signer = WbiSigner()
            wbi_refresh_hours = getattr(
                self.config.bilibili,
                "wbi_keys_refresh_hours",
                12,
            )
            self.wbi_signer.set_cache_duration(wbi_refresh_hours)
            logger.info(f"WBI signer initialized (refresh={wbi_refresh_hours}h)")
            
            # 4. 初始化 Bilibili 客户端
            self.bili_client = BiliClient(
                wbi_signer=self.wbi_signer,
                timeout=getattr(self.config.bilibili, "timeout_seconds", 10),
                user_agent=getattr(
                    self.config.bilibili,
                    "user_agent",
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                ),
                referer=getattr(
                    self.config.bilibili,
                    "referer",
                    "https://www.bilibili.com",
                ),
                cookie_sessdata=getattr(
                    self.config.bilibili,
                    "cookie_sessdata",
                    "",
                ),
                cookie_buvid3=getattr(
                    self.config.bilibili,
                    "cookie_buvid3",
                    "",
                ),
            )
            logger.info("Bilibili client initialized")
            
            # 5. 初始化群指令
            message_sender = plugin_context.send_api
            self.commands = [
                RadarAddCommand(self.dao, self.bili_client, self.config),
                RadarDelCommand(self.dao, self.config),
                RadarListCommand(self.dao),
                RadarOnCommand(self.dao, self.config),
                RadarOffCommand(self.dao, self.config),
                RadarTestCommand(self.dao, self.bili_client, message_sender, self.config),
                RadarHelpCommand(),
            ]
            
            # 注册消息处理器
            plugin_context.message_handler.register(self._handle_message)
            logger.info(f"Registered {len(self.commands)} commands")
            
            # 6. 初始化并启动后台轮询任务
            self.polling_task = BiliPollingTask(
                dao=self.dao,
                bili_client=self.bili_client,
                message_sender=message_sender,
                config=self.config,
            )
            await self.polling_task.start()
            logger.info("Polling task started")
            
            logger.info(f"{__plugin_name__} loaded successfully")
        
        except Exception as e:
            logger.error(f"Failed to load plugin: {e}", exc_info=True)
            raise
    
    async def on_unload(self) -> None:
        """插件卸载时调用"""
        try:
            # 停止后台任务
            if self.polling_task:
                await self.polling_task.stop()
                logger.info("Polling task stopped")
            
            logger.info(f"{__plugin_name__} unloaded")
        
        except Exception as e:
            logger.error(f"Failed to unload plugin: {e}", exc_info=True)
    
    async def _handle_message(self, message: Dict[str, Any]) -> None:
        """处理群消息
        
        Args:
            message: 消息对象（包含 content, stream_id, user_id, is_admin 等）
        """
        try:
            content = message.get("content", "").strip()
            stream_id = message.get("stream_id")
            user_id = message.get("user_id")
            is_admin = message.get("is_admin", False)
            
            # 遍历指令，查找匹配
            for command in self.commands:
                if await command.can_execute(content, user_id, is_admin):
                    success, reply, should_intercept = await command.execute(
                        content,
                        stream_id,
                        user_id,
                        is_admin,
                    )
                    
                    # 发送回复
                    if reply:
                        await message.reply(reply)
                    
                    # 是否拦截后续处理
                    if should_intercept:
                        break
        
        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)


# 配置 Schema 定义（根据 MaiBot 实际 API 调整）
CONFIG_SCHEMA = {
    "polling": {
        "interval_seconds": {
            "type": "integer",
            "default": 120,
            "description": "轮询间隔（秒）",
        },
        "max_concurrency": {
            "type": "integer",
            "default": 3,
            "description": "同时请求的最大 mid 数量",
        },
    },
    "bilibili": {
        "timeout_seconds": {
            "type": "integer",
            "default": 10,
            "description": "API 请求超时时间（秒）",
        },
        "user_agent": {
            "type": "string",
            "default": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "description": "User-Agent 请求头",
        },
        "referer": {
            "type": "string",
            "default": "https://www.bilibili.com",
            "description": "Referer 请求头",
        },
        "cookie_sessdata": {
            "type": "string",
            "default": "",
            "sensitive": True,
            "description": "可选：SESSDATA cookie（增强稳定性）",
        },
        "cookie_buvid3": {
            "type": "string",
            "default": "",
            "description": "可选：buvid3 cookie",
        },
        "wbi_keys_refresh_hours": {
            "type": "integer",
            "default": 12,
            "description": "WBI 密钥缓存刷新周期（小时）",
        },
    },
    "push": {
        "message_template": {
            "type": "string",
            "default": "🎬 新视频推送\n标题：{title}\n作者：{author}\n链接：{url}",
            "description": "推送消息模板（支持 {title}, {author}, {bvid}, {url}）",
        },
    },
    "permission": {
        "admin_only": {
            "type": "boolean",
            "default": True,
            "description": "是否仅管理员可修改订阅",
        },
        "operator_allowlist": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "操作员白名单（用户 ID 列表）",
        },
    },
}


# 插件导出（根据 MaiBot 实际 API 调整）
def get_plugin():
    """获取插件实例"""
    return BiliRadarPlugin()


def get_config_schema():
    """获取配置 Schema"""
    return CONFIG_SCHEMA
