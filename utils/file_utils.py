"""File utilities for Amazon Parser"""
import hashlib
import os
import re
import time
import random
from pathlib import Path
from typing import Optional, Set

import requests
from PIL import Image
from io import BytesIO

from config.settings import Settings
from utils.logger import get_logger

logger = get_logger(__name__)


def sanitize_filename(name: str, max_length: int = 100) -> str:
    """
    Sanitize filename by removing invalid characters.
    
    Args:
        name: Original filename
        max_length: Maximum length of filename
        
    Returns:
        Sanitized filename
    """
    # Remove invalid characters
    sanitized = re.sub(r'[<>:"/\\|?*]', '', name)
    # Replace multiple spaces with single space
    sanitized = re.sub(r'\s+', ' ', sanitized)
    # Remove leading/trailing spaces and dots
    sanitized = sanitized.strip(' .')
    # Truncate if too long
    if len(sanitized) > max_length:
        sanitized = sanitized[:max_length].strip()
    # Fallback if empty
    if not sanitized:
        sanitized = 'unnamed'
    return sanitized


def create_output_structure(product_name: str, include_variants: bool = False) -> str:
    """
    Create output directory structure for a product.
    If folder exists, creates (2), (3), etc.
    
    Args:
        product_name: Name of the product (will be sanitized)
        include_variants: Whether to create variants subdirectory
        
    Returns:
        Path to the product output directory
    """
    sanitized_name = sanitize_filename(product_name)
    base_dir = Path(Settings.OUTPUT_DIR) / sanitized_name
    
    # Check if folder exists, add (2), (3), etc.
    counter = 1
    while base_dir.exists():
        counter += 1
        base_dir = Path(Settings.OUTPUT_DIR) / f"{sanitized_name} ({counter})"
    
    # Don't create subdirectories here - they will be created on demand
    base_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Created output structure: {base_dir}")
    return str(base_dir)


def calculate_md5(data: bytes) -> str:
    """Calculate MD5 hash of data."""
    return hashlib.md5(data).hexdigest()


def is_excluded_url(url: str) -> bool:
    """
    Check if URL should be excluded (video, 360, ads, etc.)
    
    Args:
        url: Image URL to check
        
    Returns:
        True if URL should be excluded
    """
    url_lower = url.lower()
    for pattern in Settings.EXCLUDED_URL_PATTERNS:
        if pattern in url_lower:
            logger.debug(f"Excluded URL (pattern: {pattern}): {url[:100]}...")
            return True
    return False


def download_image(url: str) -> Optional[bytes]:
    """
    Download image from URL.
    
    Args:
        url: Image URL
        
    Returns:
        Image bytes or None if failed
    """
    try:
        headers = {
            'User-Agent': random.choice(Settings.USER_AGENTS),
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Referer': 'https://www.amazon.com/',
        }
        
        response = requests.get(url, headers=headers, timeout=30, allow_redirects=True, stream=True)
        response.raise_for_status()
        
        # Check content-length header first
        content_length = response.headers.get('content-length')
        if content_length:
            size = int(content_length)
            if size > Settings.MAX_IMAGE_SIZE:
                logger.warning(f"Image too large ({size} bytes > {Settings.MAX_IMAGE_SIZE} bytes): {url[:80]}...")
                return None
        
        # Verify it's actually an image
        content_type = response.headers.get('content-type', '').lower()
        if 'image' not in content_type:
            # Check if it's HTML (redirect or error page)
            if 'text/html' in content_type:
                logger.warning(f"Received HTML instead of image (content-type: {content_type}): {url[:100]}...")
                return None
            logger.warning(f"Not an image (content-type: {content_type}): {url[:100]}...")
            return None
        
        # Read image data with size limit
        image_data = b''
        max_size = Settings.MAX_IMAGE_SIZE
        
        for chunk in response.iter_content(chunk_size=8192):
            if chunk:
                image_data += chunk
                if len(image_data) > max_size:
                    logger.warning(f"Image exceeds size limit ({len(image_data)} bytes > {max_size} bytes): {url[:80]}...")
                    return None
        
        # Verify content is not empty
        if len(image_data) < 100:  # Too small to be a real image
            logger.warning(f"Image too small ({len(image_data)} bytes): {url[:100]}...")
            return None
        
        # Check for HTML content
        if len(image_data) > 10:
            first_bytes = image_data[:10]
            if first_bytes.startswith(b'<') or first_bytes.startswith(b'<!DOCTYPE') or first_bytes.startswith(b'<html'):
                logger.warning(f"URL returned HTML instead of image: {url[:80]}...")
                return None
        
        return image_data
        
    except requests.RequestException as e:
        logger.error(f"Failed to download image: {e}")
        return None


def _limit_md5_cache(md5_cache: Set[str]) -> None:
    """Limit MD5 cache size to prevent memory issues."""
    if len(md5_cache) > Settings.MD5_CACHE_MAX_SIZE:
        # Remove oldest entries (convert to list, remove first N, recreate set)
        # Since sets are unordered, we'll just clear and log a warning
        logger.warning(f"MD5 cache exceeded limit ({len(md5_cache)} > {Settings.MD5_CACHE_MAX_SIZE}), clearing...")
        md5_cache.clear()


def save_image_with_dedup(
    url: str, 
    output_path: str, 
    md5_cache: Set[str],
    min_size: tuple = (50, 50)
) -> bool:
    """
    Download and save image with deduplication.
    
    Args:
        url: Image URL
        output_path: Path to save the image
        md5_cache: Set of already saved image MD5 hashes
        min_size: Minimum image size (width, height)
        
    Returns:
        True if image was saved, False otherwise
    """
    # Check if URL should be excluded
    if is_excluded_url(url):
        logger.debug(f"Image excluded by URL pattern: {url[:80]}...")
        return False
    
    # Download image
    logger.debug(f"Downloading image from: {url[:80]}...")
    image_data = download_image(url)
    if not image_data:
        logger.warning(f"Failed to download image: {url[:80]}...")
        return False
    
    logger.debug(f"Downloaded {len(image_data)} bytes")
    
    # Check if it's actually an image by checking first bytes (magic numbers)
    if len(image_data) < 10:
        logger.warning(f"Image data too small: {len(image_data)} bytes")
        return False
    
    # Check image magic numbers (JPEG, PNG, WebP, GIF)
    magic = image_data[:10]
    is_image = (
        magic.startswith(b'\xff\xd8\xff') or  # JPEG
        magic.startswith(b'\x89PNG\r\n\x1a\n') or  # PNG
        (magic.startswith(b'RIFF') and b'WEBP' in magic[:12]) or  # WebP
        magic.startswith(b'GIF87a') or  # GIF87a
        magic.startswith(b'GIF89a')  # GIF89a
    )
    
    if not is_image:
        # Check if it's HTML (redirect or error page)
        if magic.strip().startswith(b'<') or b'<!DOCTYPE' in magic or b'<html' in image_data[:200]:
            logger.error(f"Downloaded HTML instead of image! URL: {url[:100]}...")
            try:
                html_preview = image_data[:500].decode('utf-8', errors='ignore')
                logger.error(f"First 500 chars of HTML response: {html_preview}")
            except:
                logger.error(f"First 100 bytes hex: {image_data[:100].hex()}")
            return False
        logger.warning(f"Unknown file format (not JPEG/PNG/WebP/GIF). Magic: {magic.hex()[:20]}...")
        logger.warning(f"URL that failed: {url[:100]}...")
        # Try to proceed anyway - maybe it's a valid image format we don't recognize
    
    # Calculate MD5 for deduplication
    md5_hash = calculate_md5(image_data)
    if md5_hash in md5_cache:
        logger.info(f"Duplicate image skipped (MD5: {md5_hash[:8]}...) - already in cache")
        return False
    
    # Verify image size
    try:
        img = Image.open(BytesIO(image_data))
        width, height = img.size
        logger.debug(f"Image size: {width}x{height}")
        if width < min_size[0] or height < min_size[1]:
            logger.warning(f"Image too small ({width}x{height}), skipped (min: {min_size[0]}x{min_size[1]})")
            return False
    except Exception as e:
        logger.error(f"Failed to verify image: {e}")
        logger.error(f"URL that failed: {url[:100]}...")
        logger.error(f"Content preview: first 100 bytes hex: {image_data[:100].hex()[:200]}")
        # Try to decode as text to see what we got
        try:
            text_preview = image_data[:200].decode('utf-8', errors='ignore')
            logger.error(f"Content preview (as text): {text_preview}")
        except:
            pass
        return False
    
    # Save image
    try:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'wb') as f:
            f.write(image_data)
        
        md5_cache.add(md5_hash)
        logger.debug(f"Saved image: {output_file.name} (MD5: {md5_hash[:8]}...)")
        
        # Random delay between downloads
        delay = random.uniform(
            Settings.IMAGE_DOWNLOAD_DELAY_MIN,
            Settings.IMAGE_DOWNLOAD_DELAY_MAX
        )
        time.sleep(delay)
        
        return True
        
    except IOError as e:
        logger.error(f"Failed to save image: {e}")
        return False


def get_high_res_url(url: str, is_aplus: bool = False) -> str:
    """
    Convert Amazon image URL to maximum resolution version by removing size indicators.
    
    For regular product images (hero, gallery):
    - ..._SL1280_.jpg -> ...jpg (Amazon returns max size)
    - ..._AC_SL500_.jpg -> ..._AC_.jpg (Amazon returns max size)
    
    For A+ content images:
    - Keep URL as-is (they have different format: _CR0,0,2928,1200_PT0_SX1464_V1__)
    - A+ URLs already contain the correct size and should not be modified
    
    Args:
        url: Original image URL
        is_aplus: If True, return URL as-is (for A+ content)
        
    Returns:
        Maximum resolution image URL (with size indicators removed for regular images)
    """
    if not url:
        return url
    
    # For A+ content, return URL as-is (don't modify)
    if is_aplus or 'aplus-media-library' in url:
        logger.debug(f"A+ URL detected, keeping as-is: {url[:60]}...")
        return url
    
    try:
        original_url = url
        high_res_url = url
        
        # Remove ALL size indicators - Amazon automatically serves max resolution when removed
        # This is the key insight: removing _SL1280_ makes Amazon return max size!
        
        # Pattern 1: _AC_SL500_, _AC_SX300_, _AC_SY200_ -> _AC_ (keep AC prefix)
        high_res_url = re.sub(r'_AC_S[LXY]\d+_', '_AC_', high_res_url)
        
        # Pattern 2: Combined sizes _AC_SX300_SY200_ -> _AC_
        high_res_url = re.sub(r'_AC_SX\d+_SY\d+_', '_AC_', high_res_url)
        
        # Pattern 3: _SL500_, _SX300_, _SY200_ (without AC) -> remove completely
        high_res_url = re.sub(r'_S[LXY]\d+_', '_', high_res_url)
        
        # Pattern 4: Handle cases like ._SL1280_.jpg -> .jpg (dot before size indicator)
        high_res_url = re.sub(r'\._S[LXY]\d+_\.', '.', high_res_url)
        
        # Pattern 5: Remove any remaining size patterns (catch-all)
        high_res_url = re.sub(r'[SLXY]\d+_', '', high_res_url)
        
        # Clean up artifacts: double dots, double underscores, underscore-dot combinations
        high_res_url = re.sub(r'\.\.+', '.', high_res_url)  # .. -> .
        high_res_url = re.sub(r'__+', '_', high_res_url)    # __ -> _
        high_res_url = re.sub(r'_\.', '.', high_res_url)    # _. -> .
        high_res_url = re.sub(r'\._', '.', high_res_url)    # ._ -> .
        
        # Log if URL changed
        if high_res_url != original_url:
            logger.debug(f"URL optimized: {original_url[:60]}... -> {high_res_url[:60]}...")
        
        return high_res_url
        
    except Exception as e:
        logger.warning(f"Error converting URL to high-res: {e}, returning original")
        return url

