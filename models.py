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


class BiliSubscription(Model):
    """Bilibili UP 主订阅表
    
    存储群聊对 UP 主的订阅关系和去重状态
    """
    
    # 主键
    id = IntegerField(primary_key=True)
    
    # 订阅关系
    stream_id = TextField(null=False, help_text="群聊天流 ID")
    mid = IntegerField(null=False, help_text="UP 主 mid")
    
    # 推送控制
    enabled = BooleanField(default=True, help_text="是否启用推送")
    
    # 去重状态（双字段判断）
    last_bvid = TextField(null=True, help_text="最近已推送的 bvid")
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
    
    @staticmethod
    async def add_subscription(
        stream_id: str,
        mid: int,
        last_bvid: Optional[str] = None,
        last_created_ts: Optional[int] = None,
    ) -> BiliSubscription:
        """添加订阅
        
        Args:
            stream_id: 群聊天流 ID
            mid: UP 主 mid
            last_bvid: 初始化的最后 bvid（可选）
            last_created_ts: 初始化的最后发布时间戳（可选）
            
        Returns:
            创建的订阅记录
            
        Raises:
            IntegrityError: 订阅已存在时抛出
        """
        subscription = BiliSubscription.create(
            stream_id=stream_id,
            mid=mid,
            enabled=True,
            last_bvid=last_bvid,
            last_created_ts=last_created_ts,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
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
        created_ts: int,
    ) -> bool:
        """更新订阅的最后视频信息
        
        Args:
            subscription_id: 订阅 ID
            bvid: 最新 bvid
            created_ts: 最新视频发布时间戳
            
        Returns:
            是否更新成功
        """
        query = BiliSubscription.update(
            last_bvid=bvid,
            last_created_ts=created_ts,
            updated_at=datetime.now(),
        ).where(BiliSubscription.id == subscription_id)
        
        updated_count = query.execute()
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
        return updated_count > 0
    
    @staticmethod
    async def create_table_if_not_exists(database) -> None:
        """创建表（如果不存在）
        
        Args:
            database: Peewee 数据库实例
        """
        BiliSubscription._meta.database = database
        database.create_tables([BiliSubscription], safe=True)
