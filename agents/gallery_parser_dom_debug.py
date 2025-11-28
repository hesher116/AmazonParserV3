"""Gallery Image Parser - DOM Debug Version with detailed logging"""
from typing import List, Optional
from pathlib import Path

from selenium.webdriver.common.by import By

from agents.base_image_parser import BaseImageParser
from utils.file_utils import save_image_with_dedup, is_excluded_url, get_high_res_url
from utils.logger import get_logger

logger = get_logger(__name__)


class GalleryParserDOMDebug(BaseImageParser):
    """
    Debug version of Gallery Parser with detailed DOM inspection.
    This version tries to extract URLs directly from DOM without clicks.
    """
    
    def parse(self, output_dir: str, hero_url: Optional[str] = None) -> List[str]:
        """
        Parse product gallery images directly from DOM (no clicks).
        With detailed logging for DOM inspection.
        
        Args:
            output_dir: Directory to save images
            hero_url: Hero image URL to exclude from gallery
            
        Returns:
            List of saved image paths
        """
        saved_images = []
        driver = self.browser.get_driver()
        
        logger.info("=" * 80)
        logger.info("GALLERY PARSING - DOM DEBUG MODE")
        logger.info("=" * 80)
        logger.info("Parsing gallery images from DOM (no clicks, direct extraction)...")
        
        # Scroll to gallery
        try:
            gallery_container = driver.find_element(By.CSS_SELECTOR, '#altImages, #imageBlock_feature_div')
            self.browser.scroll_to_element(gallery_container)
            self.browser._random_sleep(0.2, 0.4)
            logger.info("✓ Scrolled to gallery container")
        except Exception as e:
            logger.warning(f"Could not scroll to gallery: {e}")
        
        # Try multiple approaches to find thumbnails
        all_urls = []
        hero_url_normalized = None
        if hero_url:
            hero_url_normalized = self._normalize_url_for_comparison(hero_url)
            logger.info(f"Hero URL normalized: {hero_url_normalized[:80]}...")
        
        # APPROACH 1: Find li.item containers (not img, but containers)
        logger.info("-" * 80)
        logger.info("APPROACH 1: Finding li.item containers and checking their attributes")
        logger.info("-" * 80)
        
        thumbnail_containers = []
        container_selectors = [
            '#altImages ul li.item',
            '#altImages li.item',
            '#altImages li',
        ]
        
        for selector in container_selectors:
            try:
                found = driver.find_elements(By.CSS_SELECTOR, selector)
                if found:
                    thumbnail_containers = found
                    logger.info(f"✓ Found {len(thumbnail_containers)} containers with: {selector}")
                    break
            except Exception as e:
                logger.debug(f"Selector {selector} failed: {e}")
        
        if thumbnail_containers:
            logger.info(f"\nInspecting {len(thumbnail_containers)} thumbnail containers...")
            for idx, container in enumerate(thumbnail_containers, 1):
                logger.info(f"\n--- Container {idx}/{len(thumbnail_containers)} ---")
                self._inspect_container(container, idx, all_urls, hero_url_normalized)
        
        # APPROACH 2: Find img elements directly
        logger.info("-" * 80)
        logger.info("APPROACH 2: Finding img elements directly")
        logger.info("-" * 80)
        
        img_selectors = [
            '#altImages ul li.item img',
            '#altImages li img',
            '#imageBlock_feature_div img',
        ]
        
        for selector in img_selectors:
            try:
                images = driver.find_elements(By.CSS_SELECTOR, selector)
                if images:
                    logger.info(f"✓ Found {len(images)} img elements with: {selector}")
                    for idx, img in enumerate(images, 1):
                        logger.info(f"\n--- Image {idx}/{len(images)} ---")
                        self._inspect_image_element(img, idx, all_urls, hero_url_normalized)
                    if all_urls:
                        break
            except Exception as e:
                logger.debug(f"Selector {selector} failed: {e}")
        
        # Remove duplicates
        unique_urls = []
        seen = set()
        for url in all_urls:
            if url not in seen:
                unique_urls.append(url)
                seen.add(url)
        
        logger.info("=" * 80)
        logger.info(f"SUMMARY: Found {len(unique_urls)} unique gallery URLs")
        logger.info("=" * 80)
        
        # Save images
        if not unique_urls:
            logger.warning("⚠ No gallery images found in DOM")
            return saved_images
        
        gallery_dir = Path(output_dir) / 'product'
        gallery_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Downloading {len(unique_urls)} gallery images...")
        for i, url in enumerate(unique_urls, 1):
            try:
                output_path = gallery_dir / f'product{i}.jpg'
                logger.info(f"  [Download {i}/{len(unique_urls)}] Downloading product{i}.jpg...")
                logger.debug(f"  [Download {i}/{len(unique_urls)}] URL: {url[:80]}...")
                
                if save_image_with_dedup(url, str(output_path), self.md5_cache):
                    saved_images.append(str(output_path))
                    logger.info(f"  [Download {i}/{len(unique_urls)}] ✓ Saved: product{i}.jpg")
                else:
                    logger.warning(f"  [Download {i}/{len(unique_urls)}] ✗ Failed to save")
            except Exception as e:
                logger.error(f"  [Download {i}/{len(unique_urls)}] ✗ Exception: {e}")
        
        logger.info(f"✓ Gallery parsing complete: {len(saved_images)} images saved")
        return saved_images
    
    def _inspect_container(self, container, idx: int, all_urls: List[str], hero_url_normalized: Optional[str]):
        """Inspect a thumbnail container (li.item) for image URLs."""
        try:
            # Get all attributes on container
            container_attrs = {
                'data-old-hires': container.get_attribute('data-old-hires'),
                'data-a-dynamic-image': container.get_attribute('data-a-dynamic-image'),
                'data-src': container.get_attribute('data-src'),
                'class': container.get_attribute('class'),
                'id': container.get_attribute('id'),
            }
            
            logger.info(f"Container attributes:")
            for attr, value in container_attrs.items():
                if value:
                    if attr == 'data-a-dynamic-image':
                        logger.info(f"  {attr}: {value[:100]}... (truncated, full length: {len(value)})")
                    else:
                        logger.info(f"  {attr}: {value[:100]}...")
                else:
                    logger.info(f"  {attr}: None")
            
            # Try to extract URL from container itself
            url = None
            
            # 1. Check data-old-hires on container
            if container_attrs['data-old-hires']:
                url = get_high_res_url(container_attrs['data-old-hires'])
                logger.info(f"  ✓ Found URL from container.data-old-hires: {url[:80]}...")
            
            # 2. Check data-a-dynamic-image on container
            elif container_attrs['data-a-dynamic-image']:
                url = self._extract_url_from_json(container_attrs['data-a-dynamic-image'])
                if url:
                    logger.info(f"  ✓ Found URL from container.data-a-dynamic-image: {url[:80]}...")
            
            # 3. Find img inside container
            if not url:
                try:
                    img = container.find_element(By.CSS_SELECTOR, 'img')
                    logger.info(f"  Found img element inside container")
                    url = self._extract_high_res_url_from_element(img)
                    if url:
                        logger.info(f"  ✓ Found URL from img inside container: {url[:80]}...")
                except:
                    logger.info(f"  No img element found inside container")
            
            # Process URL if found
            if url and url.startswith('http') and not is_excluded_url(url):
                # Check if hero duplicate
                is_hero = False
                if hero_url_normalized:
                    url_normalized = self._normalize_url_for_comparison(url)
                    if hero_url_normalized == url_normalized:
                        is_hero = True
                        logger.info(f"  ✗ Skipped (hero duplicate)")
                
                if not is_hero:
                    all_urls.append(url)
                    logger.info(f"  ✓ Added to gallery URLs")
            elif url:
                logger.info(f"  ✗ URL excluded or invalid: {url[:80]}...")
            else:
                logger.warning(f"  ✗ No URL extracted from container")
                
        except Exception as e:
            logger.error(f"  ✗ Error inspecting container: {e}")
            import traceback
            logger.debug(traceback.format_exc())
    
    def _inspect_image_element(self, img, idx: int, all_urls: List[str], hero_url_normalized: Optional[str]):
        """Inspect an img element for image URLs."""
        try:
            # Get all attributes
            img_attrs = {
                'src': img.get_attribute('src'),
                'data-src': img.get_attribute('data-src'),
                'data-old-hires': img.get_attribute('data-old-hires'),
                'data-a-dynamic-image': img.get_attribute('data-a-dynamic-image'),
                'alt': img.get_attribute('alt'),
                'class': img.get_attribute('class'),
            }
            
            logger.info(f"Image attributes:")
            for attr, value in img_attrs.items():
                if value:
                    if attr == 'data-a-dynamic-image':
                        logger.info(f"  {attr}: {value[:100]}... (truncated)")
                    else:
                        logger.info(f"  {attr}: {value[:100]}...")
                else:
                    logger.info(f"  {attr}: None")
            
            # Check parent
            try:
                parent = img.find_element(By.XPATH, './..')
                parent_attrs = {
                    'data-old-hires': parent.get_attribute('data-old-hires'),
                    'data-a-dynamic-image': parent.get_attribute('data-a-dynamic-image'),
                    'class': parent.get_attribute('class'),
                }
                logger.info(f"Parent attributes:")
                for attr, value in parent_attrs.items():
                    if value:
                        logger.info(f"  {attr}: {value[:100]}...")
                    else:
                        logger.info(f"  {attr}: None")
            except:
                logger.info(f"  Could not inspect parent")
            
            # Extract URL
            url = self._extract_high_res_url_from_element(img)
            
            if url and url.startswith('http') and not is_excluded_url(url):
                # Check if hero duplicate
                is_hero = False
                if hero_url_normalized:
                    url_normalized = self._normalize_url_for_comparison(url)
                    if hero_url_normalized == url_normalized:
                        is_hero = True
                        logger.info(f"  ✗ Skipped (hero duplicate)")
                
                if not is_hero:
                    all_urls.append(url)
                    logger.info(f"  ✓ Added to gallery URLs: {url[:80]}...")
            elif url:
                logger.info(f"  ✗ URL excluded or invalid")
            else:
                logger.warning(f"  ✗ No URL extracted")
                
        except Exception as e:
            logger.error(f"  ✗ Error inspecting image: {e}")

