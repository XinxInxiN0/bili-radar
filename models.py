"""数据库模型与 DAO 层

定义订阅表结构和数据访问方法
"""

from datetime import datetime
from typing import List, Optional

from peewee import (
    Model,
    IntegerField,
    TextField,
    BooleanField,
    DateTimeField,
    SQL,
)

from src.common.logger import get_logger

logger = get_logger(__name__)


class BiliSubscription(Model):
    """Bilibili UP 主订阅表
    
    存储群聊对 UP 主的订阅关系和去重状态
    """
    
    # 主键
    id = IntegerField(primary_key=True)
    
    # 订阅关系
    stream_id = TextField(null=False, help_text="群聊天流 ID")
    platform = TextField(default="qq", help_text="平台标识")
    group_id = TextField(null=True, help_text="群聊天 ID (稳定标识)")
    user_id = TextField(null=True, help_text="私聊用户 ID (稳定标识)")
    mid = IntegerField(null=False, help_text="UP 主 mid")
    up_name = TextField(null=True, help_text="UP 主昵称")
    
    # 推送控制
    enabled = BooleanField(default=True, help_text="是否启用推送")
    
    # 去重状态（三字段判断）
    last_bvid = TextField(null=True, help_text="最近已推送的 bvid")
    last_title = TextField(null=True, help_text="最近已推送视频的标题")
    last_created_ts = IntegerField(null=True, help_text="最近已推送视频的发布时间戳")
    
    # 时间戳
    created_at = DateTimeField(default=datetime.now, help_text="订阅创建时间")
    updated_at = DateTimeField(default=datetime.now, help_text="最后更新时间")
    
    class Meta:
        # 表名
        table_name = "bili_subscription"
        
        # 唯一索引：同一群不能重复订阅同一 UP
        indexes = (
            (("stream_id", "mid"), True),  # True 表示唯一索引
        )


class BiliSubscriptionDAO:
    """订阅表数据访问对象
    
    提供订阅的 CRUD 操作
    """
    
    async def add_subscription(
        stream_id: str,
        mid: int,
        platform: str = "qq",
        group_id: Optional[str] = None,
        user_id: Optional[str] = None,
        up_name: Optional[str] = None,
        last_bvid: Optional[str] = None,
        last_title: Optional[str] = None,
        last_created_ts: Optional[int] = None,
    ) -> BiliSubscription:
        """添加订阅
        
        Args:
            stream_id: 群聊天流 ID
            mid: UP 主 mid
            platform: 平台标识
            group_id: 群聊天 ID
            user_id: 私聊用户 ID
            up_name: UP 主昵称
            last_bvid: 初始化的最后 bvid（可选）
            last_title: 初始化的最后标题（可选）
            last_created_ts: 初始化的最后发布时间戳（可选）
            
        Returns:
            创建的订阅记录
            
        Raises:
            IntegrityError: 订阅已存在时抛出
        """
        subscription = BiliSubscription.create(
            stream_id=stream_id,
            platform=platform,
            group_id=group_id,
            user_id=user_id,
            mid=mid,
            up_name=up_name,
            enabled=True,
            last_bvid=last_bvid,
            last_title=last_title,
            last_created_ts=last_created_ts,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        logger.debug(f"DAO: Subscription added: stream_id={stream_id}, platform={platform}, mid={mid}, up_name={up_name}")
        return subscription
    
    @staticmethod
    async def remove_subscription(stream_id: str, mid: int) -> bool:
        """删除订阅
        
        Args:
            stream_id: 群聊天流 ID
            mid: UP 主 mid
            
        Returns:
            是否删除成功（订阅存在返回 True，不存在返回 False）
        """
        query = BiliSubscription.delete().where(
            (BiliSubscription.stream_id == stream_id)
            & (BiliSubscription.mid == mid)
        )
        deleted_count = query.execute()
        if deleted_count > 0:
            logger.debug(f"DAO: Subscription removed: stream_id={stream_id}, mid={mid}")
        return deleted_count > 0
    
    @staticmethod
    async def get_subscription(stream_id: str, mid: int) -> Optional[BiliSubscription]:
        """获取单个订阅
        
        Args:
            stream_id: 群聊天流 ID
            mid: UP 主 mid
            
        Returns:
            订阅记录，不存在返回 None
        """
        try:
            subscription = BiliSubscription.get(
                (BiliSubscription.stream_id == stream_id)
                & (BiliSubscription.mid == mid)
            )
            return subscription
        except BiliSubscription.DoesNotExist:
            return None
    
    @staticmethod
    async def get_subscriptions_by_stream(stream_id: str) -> List[BiliSubscription]:
        """获取某个群的所有订阅
        
        Args:
            stream_id: 群聊天流 ID
            
        Returns:
            订阅列表
        """
        subscriptions = list(
            BiliSubscription.select().where(
                BiliSubscription.stream_id == stream_id
            ).order_by(BiliSubscription.created_at.desc())
        )
        return subscriptions
    
    @staticmethod
    async def get_all_enabled_subscriptions() -> List[BiliSubscription]:
        """获取所有启用的订阅
        
        用于后台轮询任务
        
        Returns:
            所有 enabled=True 的订阅列表
        """
        subscriptions = list(
            BiliSubscription.select().where(
                BiliSubscription.enabled == True  # noqa: E712
            )
        )
        return subscriptions
    
    @staticmethod
    async def update_last_video(
        subscription_id: int,
        bvid: str,
        title: str,
        created_ts: int,
        up_name: Optional[str] = None,
    ) -> bool:
        """更新订阅的最后视频信息
        
        Args:
            subscription_id: 订阅 ID
            bvid: 最新 bvid
            title: 最新视频标题
            created_ts: 最新视频发布时间戳
            up_name: 更新 UP 主昵称（可选）
            
        Returns:
            是否更新成功
        """
        update_data = {
            "last_bvid": bvid,
            "last_title": title,
            "last_created_ts": created_ts,
            "updated_at": datetime.now(),
        }
        if up_name:
            update_data["up_name"] = up_name
            
        query = BiliSubscription.update(**update_data).where(BiliSubscription.id == subscription_id)
        
        updated_count = query.execute()
        if updated_count > 0:
            logger.debug(f"DAO: Updated last video for subscription_id={subscription_id}: bvid={bvid}, title={title}")
        return updated_count > 0
    
    @staticmethod
    async def toggle_enabled(stream_id: str, mid: int, enabled: bool) -> bool:
        """切换订阅的启用状态
        
        Args:
            stream_id: 群聊天流 ID
            mid: UP 主 mid
            enabled: 是否启用
            
        Returns:
            是否更新成功（订阅不存在返回 False）
        """
        query = BiliSubscription.update(
            enabled=enabled,
            updated_at=datetime.now(),
        ).where(
            (BiliSubscription.stream_id == stream_id)
            & (BiliSubscription.mid == mid)
        )
        
        updated_count = query.execute()
        if updated_count > 0:
            logger.debug(f"DAO: Toggled enabled={enabled} for stream_id={stream_id}, mid={mid}")
        return updated_count > 0
    
    @staticmethod
    async def create_table_if_not_exists(database) -> None:
        """创建表（如果不存在）并处理迁移
        
        Args:
            database: Peewee 数据库实例
        """
        BiliSubscription._meta.database = database
        database.create_tables([BiliSubscription], safe=True)
        
        # 简单的数据库迁移：检查缺失的列并添加
        try:
            columns = [c.name for c in database.get_columns("bili_subscription")]
            
            if "up_name" not in columns:
                logger.info("Migrating: Adding column 'up_name' to 'bili_subscription'")
                database.execute_sql('ALTER TABLE bili_subscription ADD COLUMN up_name TEXT;')
                
            if "last_title" not in columns:
                logger.info("Migrating: Adding column 'last_title' to 'bili_subscription'")
                database.execute_sql('ALTER TABLE bili_subscription ADD COLUMN last_title TEXT;')
            
            if "platform" not in columns:
                logger.info("Migrating: Adding column 'platform' to 'bili_subscription'")
                database.execute_sql("ALTER TABLE bili_subscription ADD COLUMN platform TEXT DEFAULT 'qq';")

            if "group_id" not in columns:
                logger.info("Migrating: Adding column 'group_id' to 'bili_subscription'")
                database.execute_sql("ALTER TABLE bili_subscription ADD COLUMN group_id TEXT;")
            
            if "user_id" not in columns:
                logger.info("Migrating: Adding column 'user_id' to 'bili_subscription'")
                database.execute_sql("ALTER TABLE bili_subscription ADD COLUMN user_id TEXT;")
                
        except Exception as e:
            logger.error(f"Migration error: {e}")
