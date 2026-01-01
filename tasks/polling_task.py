"""后台轮询任务

定期检查订阅的 UP 主是否发布新视频，并推送到订阅群
"""

import asyncio
from typing import Dict, List, Set
import logging

logger = logging.getLogger(__name__)


class BiliPollingTask:
    """Bilibili UP 主新视频轮询任务
    
    周期性抓取所有订阅 UP 的最新视频，检测到新视频后推送到订阅群
    """
    
    def __init__(
        self,
        dao,
        bili_client,
        message_sender,
        config,
    ):
        """初始化轮询任务
        
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
        
        # 任务控制
        self._running = False
        self._task = None
    
    async def start(self) -> None:
        """启动轮询任务"""
        if self._running:
            logger.warning("Polling task already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Polling task started")
    
    async def stop(self) -> None:
        """停止轮询任务"""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Polling task stopped")
    
    async def _run_loop(self) -> None:
        """轮询主循环"""
        interval = getattr(self.config.polling, "interval_seconds", 120)
        logger.info(f"Polling loop started with interval={interval}s")
        
        while self._running:
            try:
                await self._poll_once()
            except Exception as e:
                logger.error(f"Error in polling loop: {e}", exc_info=True)
            
            # 等待下一个周期
            await asyncio.sleep(interval)
    
    async def _poll_once(self) -> None:
        """执行一次轮询"""
        logger.debug("Starting polling cycle")
        
        try:
            # 1. 获取所有启用的订阅
            subscriptions = await self.dao.get_all_enabled_subscriptions()
            
            if not subscriptions:
                logger.debug("No enabled subscriptions, skipping")
                return
            
            # 2. 按 mid 去重聚合
            unique_mids: Set[int] = {sub.mid for sub in subscriptions}
            logger.info(
                f"Polling cycle: {len(subscriptions)} subscriptions, "
                f"{len(unique_mids)} unique mids"
            )
            
            # 3. 并发抓取所有 mid 的最新视频
            max_concurrency = getattr(self.config.polling, "max_concurrency", 3)
            mid_to_video = await self._fetch_latest_videos_batch(
                list(unique_mids),
                max_concurrency,
            )
            
            logger.info(
                f"Fetched {len(mid_to_video)}/{len(unique_mids)} videos successfully"
            )
            
            # 4. 遍历订阅，判断是否需要推送
            push_count = 0
            for subscription in subscriptions:
                try:
                    latest_video = mid_to_video.get(subscription.mid)
                    if not latest_video:
                        continue
                    
                    # 判断是否为新视频（双条件）
                    if self._should_push(latest_video, subscription):
                        # 推送并更新
                        await self._push_and_update(latest_video, subscription)
                        push_count += 1
                
                except Exception as e:
                    logger.error(
                        f"Failed to process subscription {subscription.id}: {e}",
                        exc_info=True,
                    )
                    continue
            
            logger.info(f"Polling cycle completed: {push_count} videos pushed")
        
        except Exception as e:
            logger.error(f"Error in poll_once: {e}", exc_info=True)
    
    async def _fetch_latest_videos_batch(
        self,
        mid_list: List[int],
        max_concurrency: int,
    ) -> Dict[int, any]:
        """批量抓取最新视频（带并发控制）
        
        Args:
            mid_list: mid 列表
            max_concurrency: 最大并发数
            
        Returns:
            {mid: VideoInfo} 字典
        """
        semaphore = asyncio.Semaphore(max_concurrency)
        
        async def fetch_with_semaphore(mid: int):
            async with semaphore:
                return mid, await self.bili_client.fetch_latest_video(mid)
        
        # 并发执行
        tasks = [fetch_with_semaphore(mid) for mid in mid_list]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 过滤成功的结果
        mid_to_video = {}
        for result in results:
            if isinstance(result, Exception):
                logger.error(f"Fetch failed: {result}")
                continue
            
            mid, video = result
            if video:
                mid_to_video[mid] = video
        
        return mid_to_video
    
    def _should_push(self, latest_video, subscription) -> bool:
        """判断是否应该推送
        
        使用双条件判断，避免 UP 删除重发导致的误判
        
        Args:
            latest_video: VideoInfo 对象
            subscription: BiliSubscription 对象
            
        Returns:
            是否应该推送
        """
        # 如果没有历史记录，不推送（初次订阅时已记录基准）
        if not subscription.last_bvid or not subscription.last_created_ts:
            return False
        
        # 双条件判断
        is_new = (
            latest_video.bvid != subscription.last_bvid
            and latest_video.created_ts > subscription.last_created_ts
        )
        
        if is_new:
            logger.debug(
                f"New video detected: mid={subscription.mid}, "
                f"bvid={latest_video.bvid}, "
                f"prev_bvid={subscription.last_bvid}"
            )
        
        return is_new
    
    async def _push_and_update(self, video, subscription) -> None:
        """推送消息并更新订阅记录
        
        Args:
            video: VideoInfo 对象
            subscription: BiliSubscription 对象
        """
        try:
            # 生成推送消息
            template = getattr(
                self.config.push,
                "message_template",
                "🎬 新视频推送\n标题：{title}\n作者：{author}\n链接：{url}",
            )
            message = template.format(
                title=video.title,
                author=video.author,
                bvid=video.bvid,
                url=video.url,
            )
            
            # 发送到目标群
            await self.message_sender.text_to_stream(subscription.stream_id, message)
            
            # 更新订阅的 last_* 字段
            await self.dao.update_last_video(
                subscription.id,
                video.bvid,
                video.created_ts,
            )
            
            logger.info(
                f"Pushed new video: stream_id={subscription.stream_id}, "
                f"mid={subscription.mid}, bvid={video.bvid}"
            )
        
        except Exception as e:
            logger.error(
                f"Failed to push and update: stream_id={subscription.stream_id}, "
                f"mid={subscription.mid}, error={e}",
                exc_info=True,
            )
            raise
