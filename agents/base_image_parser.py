"""Base class for image parsers with common functionality"""
import re
from typing import Optional, Set
from pathlib import Path

from selenium.webdriver.common.by import By

from core.browser_pool import BrowserPool
from utils.file_utils import save_image_with_dedup, get_high_res_url, is_excluded_url
from utils.logger import get_logger

logger = get_logger(__name__)


class BaseImageParser:
    """Base class for all image parsers with shared functionality."""
    
    def __init__(self, browser_pool: BrowserPool, md5_cache: Set[str] = None):
        self.browser = browser_pool
        self.md5_cache = md5_cache if md5_cache is not None else set()
    
    def _extract_high_res_url_from_element(self, element) -> Optional[str]:
        """
        Extract high-resolution URL from image element.
        For gallery thumbnails, checks parent elements and data-a-dynamic-image JSON.
        
        Priority:
        1. data-old-hires (direct high-res) - на елементі або батьківському
        2. data-a-dynamic-image (JSON with all sizes) - вибрати найбільший
        3. data-src (lazy-loaded) - але перевірити розмір
        4. src (fallback) - тільки якщо не маленький thumbnail
        
        Args:
            element: Selenium WebElement with image
            
        Returns:
            High-resolution URL or None
        """
        # 1. data-old-hires - найкращий варіант (direct high-res)
        url = element.get_attribute('data-old-hires')
        if url and url.startswith('http'):
            logger.debug(f"Found data-old-hires on element: {url[:60]}...")
            return get_high_res_url(url)
        
        # Перевірити на батьківському елементі (для gallery thumbnails - li.item)
        try:
            parent = element.find_element(By.XPATH, './..')
            url = parent.get_attribute('data-old-hires')
            if url and url.startswith('http'):
                logger.debug(f"Found data-old-hires on parent: {url[:60]}...")
                return get_high_res_url(url)
        except:
            pass
        
        # 2. data-a-dynamic-image - JSON з усіма розмірами (найважливіше для gallery!)
        json_data = element.get_attribute('data-a-dynamic-image')
        if json_data:
            url = self._extract_url_from_json(json_data)
            if url:
                return url
        
        # Перевірити на батьківському елементі (для gallery thumbnails)
        try:
            parent = element.find_element(By.XPATH, './..')
            json_data = parent.get_attribute('data-a-dynamic-image')
            if json_data:
                url = self._extract_url_from_json(json_data)
                if url:
                    return url
        except:
            pass
        
        # 3. data-src (lazy-loaded) - перевірити чи не маленький thumbnail
        url = element.get_attribute('data-src')
        if url and url.startswith('http'):
            if not re.search(r'[SLXY](40|50|75|100|150|200)[^0-9]', url):
                logger.debug(f"Using data-src: {url[:60]}...")
                return get_high_res_url(url)
            else:
                logger.debug(f"Skipped small thumbnail in data-src: {url[:60]}...")
        
        # 4. src (fallback) - тільки якщо не маленький thumbnail і не SVG/іконка
        url = element.get_attribute('src')
        if url and url.startswith('http'):
            # Перевірити чи не SVG/іконка
            if '/sash/' in url or url.endswith('.svg'):
                logger.debug(f"Skipped SVG/icon in src: {url[:60]}...")
                return None
            
            # Перевірити чи не маленький thumbnail
            if not re.search(r'[SLXY](40|50|75|100|150|200)[^0-9]', url):
                logger.debug(f"Using src: {url[:60]}...")
                return get_high_res_url(url)
            else:
                logger.debug(f"Skipped small thumbnail in src: {url[:60]}...")
        
        logger.debug(f"Could not extract high-res URL from element")
        return None
    
    def _extract_url_from_json(self, json_data: str) -> Optional[str]:
        """
        Extract highest resolution URL from data-a-dynamic-image JSON.
        
        Args:
            json_data: JSON string from data-a-dynamic-image attribute
            
        Returns:
            Highest resolution URL or None
        """
        try:
            import json
            data = json.loads(json_data)
            # data = {"url1": [width, height], "url2": [width, height]}
            if data:
                # Знайти найбільший розмір (width * height)
                best_url, best_size = max(data.items(), key=lambda x: x[1][0] * x[1][1] if len(x[1]) >= 2 else 0)
                logger.debug(f"Found best URL from JSON: {best_url[:60]}... (size: {best_size})")
                return get_high_res_url(best_url)
        except json.JSONDecodeError:
            # Fallback: regex extraction if JSON invalid
            urls = re.findall(r'"(https://[^"]+)"', json_data)
            if urls:
                best_url = max(urls, key=lambda u: self._get_image_size_from_url(u))
                logger.debug(f"Found best URL from JSON (regex): {best_url[:60]}...")
                return get_high_res_url(best_url)
        except Exception as e:
            logger.debug(f"Error parsing JSON: {e}")
        
        return None
    
    def _get_image_size_from_url(self, url: str) -> int:
        """Extract image size from URL for comparison."""
        match = re.search(r'[SLXY](\d+)', url)
        if match:
            return int(match.group(1))
        return 0
    
    def _normalize_url_for_comparison(self, url: str) -> str:
        """
        Normalize URL for comparison (remove query params, fragments, size indicators).
        
        Args:
            url: Original URL
            
        Returns:
            Normalized URL
        """
        if not url:
            return url
        
        # Remove query parameters and fragments
        normalized = url.split('?')[0].split('#')[0]
        
        # Remove size indicators for comparison
        normalized = re.sub(r'_AC_S[LXY]\d+_', '_AC_', normalized)
        normalized = re.sub(r'_S[LXY]\d+_', '_', normalized)
        
        return normalized
    
    def _is_video_thumbnail(self, element) -> bool:
        """Check if element is a video thumbnail."""
        try:
            # Check for play button overlay
            parent = element.find_element(By.XPATH, './..')
            play_buttons = parent.find_elements(By.CSS_SELECTOR, '.play-button, .video-play, [aria-label*="video"]')
            if play_buttons:
                return True
            
            # Check alt text
            alt = element.get_attribute('alt') or ''
            if 'video' in alt.lower() or 'play' in alt.lower():
                return True
            
            # Check URL
            src = element.get_attribute('src') or ''
            if 'video' in src.lower():
                return True
        except:
            pass
        
        return False

