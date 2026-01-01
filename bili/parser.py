"""Bilibili API 数据解析器

解析 API 响应，提取视频信息
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class VideoInfo:
    """视频信息数据类"""
    
    bvid: str
    title: str
    author: str
    created_ts: int  # Unix timestamp
    
    @property
    def url(self) -> str:
        """生成视频链接"""
        return f"https://www.bilibili.com/video/{self.bvid}"
    
    def __str__(self) -> str:
        return f"VideoInfo(bvid={self.bvid}, title={self.title[:20]}...)"


class BiliParser:
    """Bilibili API 响应解析器"""
    
    @staticmethod
    def parse_latest_video(response_data: Dict[str, Any]) -> Optional[VideoInfo]:
        """从投稿列表响应中解析最新视频
        
        Args:
            response_data: API 响应的 data 字段
            
        Returns:
            VideoInfo 对象，解析失败返回 None
        """
        try:
            # 检查响应结构
            if not response_data:
                logger.warning("Response data is empty")
                return None
            
            # 获取视频列表
            vlist = response_data.get("list", {}).get("vlist", [])
            if not vlist:
                logger.info("No videos found in vlist")
                return None
            
            # 取第一条（最新）
            latest = vlist[0]
            
            # 提取字段
            bvid = latest.get("bvid")
            title = latest.get("title")
            author = latest.get("author")
            created_ts = latest.get("created")
            
            # 验证必需字段
            if not all([bvid, title, created_ts]):
                logger.warning(f"Missing required fields in video data: {latest}")
                return None
            
            return VideoInfo(
                bvid=bvid,
                title=title,
                author=author or "未知UP主",
                created_ts=created_ts,
            )
            
        except Exception as e:
            logger.error(f"Failed to parse video info: {e}", exc_info=True)
            return None
