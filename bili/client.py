"""Bilibili API 客户端

封装投稿列表查询接口，处理 WBI 签名和错误
"""

from typing import Optional, Dict, Any
import logging

import httpx

from .wbi_signer import WbiSigner
from .parser import BiliParser, VideoInfo

logger = logging.getLogger(__name__)


class BiliClient:
    """Bilibili API 客户端"""
    
    # 投稿列表接口（WBI 签名）
    ARC_SEARCH_URL = "https://api.bilibili.com/x/space/wbi/arc/search"
    
    def __init__(
        self,
        wbi_signer: WbiSigner,
        timeout: int = 10,
        user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        referer: str = "https://www.bilibili.com",
        cookie_sessdata: str = "",
        cookie_buvid3: str = "",
    ):
        """初始化客户端
        
        Args:
            wbi_signer: WBI 签名器实例
            timeout: 请求超时时间（秒）
            user_agent: User-Agent 请求头
            referer: Referer 请求头
            cookie_sessdata: 可选的 SESSDATA cookie
            cookie_buvid3: 可选的 buvid3 cookie
        """
        self.wbi_signer = wbi_signer
        self.timeout = timeout
        
        # 请求头
        self.headers = {
            "User-Agent": user_agent,
            "Referer": referer,
        }
        
        # Cookies（可选）
        self.cookies: Dict[str, str] = {}
        if cookie_sessdata:
            self.cookies["SESSDATA"] = cookie_sessdata
            logger.info(f"SESSDATA configured (length={len(cookie_sessdata)})")
        if cookie_buvid3:
            self.cookies["buvid3"] = cookie_buvid3
            logger.info(f"buvid3 configured (length={len(cookie_buvid3)})")
    
    async def fetch_latest_video(
        self,
        mid: int,
        retry_on_sign_error: bool = True,
    ) -> Optional[VideoInfo]:
        """获取 UP 主的最新视频
        
        Args:
            mid: UP 主 mid
            retry_on_sign_error: 签名错误时是否刷新密钥并重试
            
        Returns:
            VideoInfo 对象，失败返回 None
        """
        try:
            # 构造请求参数
            params = {
                "mid": mid,
                "order": "pubdate",  # 按发布时间排序
                "pn": 1,
                "ps": 1,  # 只取最新 1 条
            }
            
            # 添加 WBI 签名
            signed_params = await self.wbi_signer.sign_params(params)
            
            # 发送请求
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    self.ARC_SEARCH_URL,
                    params=signed_params,
                    headers=self.headers,
                    cookies=self.cookies,
                )
                response.raise_for_status()
                data = response.json()
            
            # 检查响应 code
            code = data.get("code")
            
            # -412: 风控拦截
            if code == -412:
                logger.warning(f"Request blocked by anti-bot (mid={mid}, code=-412)")
                return None
            
            # 签名相关错误（可能包含 v_voucher）
            if code != 0:
                message = data.get("message", "Unknown error")
                logger.warning(f"API returned error for mid={mid}: code={code}, message={message}")
                
                # 如果允许重试且未重试过
                if retry_on_sign_error and "sign" in message.lower():
                    logger.info(f"Possible signature error, refreshing WBI keys and retrying (mid={mid})")
                    await self.wbi_signer.refresh_keys()
                    # 递归重试一次（retry_on_sign_error=False 避免无限循环）
                    return await self.fetch_latest_video(mid, retry_on_sign_error=False)
                
                return None
            
            # 解析视频信息
            video_info = BiliParser.parse_latest_video(data.get("data"))
            
            if video_info:
                logger.debug(f"Fetched latest video for mid={mid}: {video_info}")
            else:
                logger.info(f"No videos found for mid={mid}")
            
            return video_info
            
        except httpx.TimeoutException:
            logger.error(f"Request timeout for mid={mid}")
            return None
        
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error for mid={mid}: {e.response.status_code}")
            return None
        
        except Exception as e:
            logger.error(f"Failed to fetch latest video for mid={mid}: {e}", exc_info=True)
            return None
