"""Bilibili WBI 签名器

实现 WBI 签名生成和密钥管理
文档：https://socialsisteryi.github.io/bilibili-API-collect/docs/misc/sign/wbi.html
"""

import hashlib
import time
from typing import Dict, Optional, Tuple
from urllib.parse import urlencode
import httpx

from src.common.logger import get_logger

logger = get_logger(__name__)


class WbiSigner:
    """WBI 签名器
    
    负责获取和缓存 WBI 密钥，生成签名参数
    """
    
    # 混淆映射表（按文档固定顺序）
    MIXIN_KEY_ENC_TAB = [
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
        33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40,
        61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11,
        36, 20, 34, 44, 52
    ]
    
    def __init__(
        self,
        nav_url: str = "https://api.bilibili.com/x/web-interface/nav",
        headers: Optional[Dict[str, str]] = None,
    ):
        """初始化 WBI 签名器
        
        Args:
            nav_url: 获取 WBI 密钥的 API 地址
            headers: 默认请求头
        """
        self.nav_url = nav_url
        self.headers = headers or {}
        
        # 密钥缓存
        self._img_key: Optional[str] = None
        self._sub_key: Optional[str] = None
        self._keys_fetched_at: float = 0
        
        # 缓存时长（秒），由外部配置注入
        self._cache_duration: int = 12 * 3600  # 默认 12 小时
    
    def set_cache_duration(self, hours: int) -> None:
        """设置密钥缓存时长
        
        Args:
            hours: 缓存时长（小时）
        """
        self._cache_duration = hours * 3600
    
    async def get_mixin_key(self, force_refresh: bool = False) -> str:
        """获取混淆后的 mixin_key
        
        Args:
            force_refresh: 是否强制刷新密钥
            
        Returns:
            混淆后的 mixin_key（32 字符）
            
        Raises:
            Exception: 获取密钥失败
        """
        # 检查是否需要刷新
        if force_refresh or not self._is_keys_valid():
            await self._fetch_wbi_keys()
        
        # 拼接原始 key
        orig_key = self._img_key + self._sub_key
        
        # 按混淆表重排
        mixin_key = "".join([orig_key[i] for i in self.MIXIN_KEY_ENC_TAB])
        
        # 截取前 32 位
        return mixin_key[:32]
    
    async def sign_params(self, params: Dict[str, any]) -> Dict[str, any]:
        """为参数添加 WBI 签名
        
        Args:
            params: 原始请求参数
            
        Returns:
            添加了 wts 和 w_rid 的参数字典
        """
        try:
            # 获取 mixin_key
            mixin_key = await self.get_mixin_key()
            
            # 添加时间戳
            params["wts"] = int(time.time())
            
            # 按 key 字母序排序并拼接
            sorted_params = sorted(params.items())
            query = urlencode(sorted_params)
            
            # 计算 MD5
            w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
            
            # 添加签名
            params["w_rid"] = w_rid
            
            return params
            
        except Exception as e:
            logger.error(f"Failed to sign params: {e}", exc_info=True)
            raise
    
    async def _fetch_wbi_keys(self) -> None:
        """从 nav 接口获取 WBI 密钥
        
        Raises:
            Exception: 请求失败或解析失败
        """
        try:
            logger.info("Fetching WBI keys from nav API")
            
            async with httpx.AsyncClient(timeout=10.0, headers=self.headers) as client:
                response = await client.get(self.nav_url)
                response.raise_for_status()
                data = response.json()
            
            # 提取 img_url 和 sub_url（无需检查 code，未登录状态也会返回有效数据）
            wbi_img = data.get("data", {}).get("wbi_img", {})
            img_url = wbi_img.get("img_url")
            sub_url = wbi_img.get("sub_url")
            
            if not img_url or not sub_url:
                raise Exception(f"Missing wbi_img urls in response: {wbi_img}")
            
            # 从 URL 中提取 key（文件名去除扩展名）
            self._img_key = img_url.split("/")[-1].split(".")[0]
            self._sub_key = sub_url.split("/")[-1].split(".")[0]
            self._keys_fetched_at = time.time()
            
            logger.info(
                f"WBI keys fetched successfully: img_key={self._img_key[:4]}..., sub_key={self._sub_key[:4]}..."
            )
            
        except Exception as e:
            logger.error(f"Failed to fetch WBI keys: {e}", exc_info=True)
            raise
    
    def _is_keys_valid(self) -> bool:
        """检查密钥缓存是否有效
        
        Returns:
            缓存有效返回 True
        """
        if not self._img_key or not self._sub_key:
            return False
        
        elapsed = time.time() - self._keys_fetched_at
        return elapsed < self._cache_duration
    
    async def refresh_keys(self) -> None:
        """强制刷新密钥（签名失败时调用）"""
        logger.warning("Force refreshing WBI keys")
        await self._fetch_wbi_keys()
