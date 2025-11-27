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


def create_variant_structure(base_dir: str, variant_name: str) -> str:
    """
    Create output structure for a product variant.
    
    Args:
        base_dir: Base product directory
        variant_name: Name of the variant (will be sanitized)
        
    Returns:
        Path to the variant output directory
    """
    sanitized_name = sanitize_filename(variant_name)
    variant_dir = Path(base_dir) / 'variants' / sanitized_name
    
    subdirs = ['hero', 'product', 'aplus_brand', 'aplus_product', 'QAImages']
    for subdir in subdirs:
        (variant_dir / subdir).mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Created variant structure: {variant_dir}")
    return str(variant_dir)


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
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Verify it's actually an image
        content_type = response.headers.get('content-type', '')
        if 'image' not in content_type:
            logger.warning(f"Not an image (content-type: {content_type}): {url[:100]}...")
            return None
        
        return response.content
        
    except requests.RequestException as e:
        logger.error(f"Failed to download image: {e}")
        return None


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
        return False
    
    # Download image
    image_data = download_image(url)
    if not image_data:
        return False
    
    # Calculate MD5 for deduplication
    md5_hash = calculate_md5(image_data)
    if md5_hash in md5_cache:
        logger.debug(f"Duplicate image skipped (MD5: {md5_hash})")
        return False
    
    # Verify image size
    try:
        img = Image.open(BytesIO(image_data))
        width, height = img.size
        if width < min_size[0] or height < min_size[1]:
            logger.debug(f"Image too small ({width}x{height}), skipped")
            return False
    except Exception as e:
        logger.warning(f"Failed to verify image: {e}")
        return False
    
    # Save image
    try:
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'wb') as f:
            f.write(image_data)
        
        md5_cache.add(md5_hash)
        logger.info(f"Saved image: {output_file.name}")
        
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


def get_high_res_url(url: str) -> str:
    """
    Convert Amazon image URL to high resolution version.
    Removes size restrictions from URL (e.g., _AC_SL1500_ -> high resolution).
    
    Based on algorithm: remove size part from URL if it exists.
    
    Args:
        url: Original image URL
        
    Returns:
        High resolution image URL
    """
    if not url:
        return url
    
    try:
        # Method 1: Remove size part from URL (e.g., _AC_SL1500_)
        # Split by dots to find parts with size indicators
        parts = url.split('.')
        
        # If we have parts like: ..._AC_SL1500_.jpg
        if len(parts) > 2:
            # Find and remove size part (usually second to last before extension)
            new_parts = []
            for i, part in enumerate(parts):
                # Skip parts that look like size indicators
                if i < len(parts) - 1:  # Not the last part (extension)
                    # Check if this part contains size pattern
                    if re.match(r'^_[A-Z]{2,}_[A-Z]*\d*_?$', part) or \
                       re.match(r'^_[A-Z]+\d+_?$', part) or \
                       re.match(r'^_S[XY]\d+_?$', part):
                        continue  # Skip this size part
                new_parts.append(part)
            
            if len(new_parts) < len(parts):
                url = '.'.join(new_parts)
        
        # Method 2: Regex replacement (fallback)
        patterns = [
            r'\._[A-Z]{2,}_[A-Z]*\d*_',  # ._AC_SL1500_, ._SX300_, etc.
            r'\._[A-Z]+\d+_',            # ._SL500_, etc.
            r'_S[XY]\d+_',               # _SX300_, _SY200_
        ]
        
        high_res_url = url
        for pattern in patterns:
            high_res_url = re.sub(pattern, '.', high_res_url)
        
        return high_res_url
        
    except Exception:
        return url

