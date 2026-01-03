"""后台轮询任务

定期检查订阅的 UP 主是否发布新视频，并推送到订阅群
"""

import asyncio
from typing import Dict, List, Set
from src.common.logger import get_logger

logger = get_logger(__name__)

import httpx
from src.plugin_system.apis import send_api, chat_api


class BiliPollingTask:
    """Bilibili UP 主新视频轮询任务
    
    周期性抓取所有订阅 UP 的最新视频，检测到新视频后推送到订阅群
    """
    
    def __init__(
        self,
        dao,
        bili_client,
        send_api_module,
        config,
    ):
        """初始化轮询任务
        
        Args:
            dao: BiliSubscriptionDAO 实例
            bili_client: BiliClient 实例
            send_api_module: send_api 模块
            config: 插件配置对象
        """
        self.dao = dao
        self.bili_client = bili_client
        self.send_api = send_api_module
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
        interval = self.config.get_config("polling.interval_seconds", 120)
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
        logger.debug("BiliPolling: Starting polling cycle")
        
        try:
            # 1. 获取所有启用的订阅
            subscriptions = await self.dao.get_all_enabled_subscriptions()
            
            if not subscriptions:
                logger.debug("No enabled subscriptions, skipping")
                return
            
            # 2. 按 mid 去重聚合
            unique_mids: Set[int] = {sub.mid for sub in subscriptions}
            logger.info(
                f"BiliPolling: Polling cycle: {len(subscriptions)} subscriptions, "
                f"{len(unique_mids)} unique mids"
            )
            
            # 3. 使用共享 Client 并发抓取所有 mid 的最新视频
            timeout = self.config.get_config("bilibili.timeout_seconds", 10)
            max_concurrency = self.config.get_config("polling.max_concurrency", 3)
            
            async with httpx.AsyncClient(timeout=timeout) as client:
                mid_to_video = await self._fetch_latest_videos_batch(
                    list(unique_mids),
                    max_concurrency,
                    client,
                )
            
            logger.debug(
                f"BiliPolling: Fetched {len(mid_to_video)}/{len(unique_mids)} videos successfully"
            )
            
            # 4. 遍历订阅，判断是否需要推送或补全初始化
            push_count = 0
            initialized_count = 0
            
            for subscription in subscriptions:
                try:
                    latest_video = mid_to_video.get(subscription.mid)
                    if not latest_video:
                        continue
                    
                    # 补全初始化 (Healing logic): 如果没有历史记录，则只更新基准不推送
                    if not subscription.last_bvid or not subscription.last_created_ts:
                        await self.dao.update_last_video(
                            subscription_id=subscription.id,
                            bvid=latest_video.bvid,
                            title=latest_video.title,
                            created_ts=latest_video.created_ts,
                            up_name=latest_video.author,
                        )
                        initialized_count += 1
                        logger.info(f"Healed subscription baseline for {latest_video.author}({subscription.mid})")
                        continue
                    
                    # 正常判断是否为新视频
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
            
            logger.info(
                f"BiliPolling: Polling cycle completed: {push_count} pushed, "
                f"{initialized_count} healed"
            )
        
        except Exception as e:
            logger.error(f"Error in poll_once: {e}", exc_info=True)
    
    async def _fetch_latest_videos_batch(
        self,
        mid_list: List[int],
        max_concurrency: int,
        client: httpx.AsyncClient,
    ) -> Dict[int, any]:
        """批量抓取最新视频（带并发控制）
        
        Args:
            mid_list: mid 列表
            max_concurrency: 最大并发数
            client: 共享的 httpx 客户端
            
        Returns:
            {mid: VideoInfo} 字典
        """
        semaphore = asyncio.Semaphore(max_concurrency)
        
        async def fetch_with_semaphore(mid: int):
            async with semaphore:
                return mid, await self.bili_client.fetch_latest_video(mid, client=client)
        
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
        # 如果没有历史记录，交由 _poll_once 的 healing 逻辑处理
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
            template = self.config.get_config(
                "push.message_template",
                "🎬 新视频推送\n标题：{title}\n作者：{author}\n链接：{url}",
            )
            
            message = template.format(
                title=video.title,
                author=video.author,
                bvid=video.bvid,
                url=video.url,
            )
            
            # 发送到目标群 (不存储消息，防止Bot自我回路过滤)
            # CRITICAL FIX: Parameter order was swapped (text, stream_id)
            success = await self.send_api.text_to_stream(message, subscription.stream_id, storage_message=False)

            # Healing logic: if push failed, try to recover stream_id
            if not success:
                logger.warning(f"Push failed for stream_id={subscription.stream_id}, attempting to heal...")
                new_stream = None
                if subscription.group_id:
                    new_stream = chat_api.get_stream_by_group_id(subscription.group_id, platform=subscription.platform)
                elif subscription.user_id:
                    new_stream = chat_api.get_stream_by_user_id(subscription.user_id, platform=subscription.platform)
                
                if new_stream and new_stream.stream_id != subscription.stream_id:
                    logger.info(f"Recovered new stream_id={new_stream.stream_id} for subscription {subscription.id}")
                    # Retry with new stream_id
                    success = await self.send_api.text_to_stream(message, new_stream.stream_id, storage_message=False)
                    if success:
                        # Update the stream_id in database for next time
                        subscription.stream_id = new_stream.stream_id
                        subscription.save()
                        logger.info(f"Successfully retried push and updated stream_id for subscription {subscription.id}")
                else:
                    logger.error(f"Failed to heal stream for subscription {subscription.id}")

            # 更新订阅的 last_* 字段
            await self.dao.update_last_video(
                subscription_id=subscription.id,
                bvid=video.bvid,
                title=video.title,
                created_ts=video.created_ts,
                up_name=video.author,
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
