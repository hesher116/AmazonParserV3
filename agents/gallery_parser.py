"""Gallery Image Parser - Parses product gallery images"""
import json
import re
from typing import List, Optional
from pathlib import Path

from selenium.webdriver.common.by import By

from agents.base_image_parser import BaseImageParser
from utils.file_utils import save_image_with_dedup, is_excluded_url, get_high_res_url
from utils.logger import get_logger

logger = get_logger(__name__)


class GalleryParser(BaseImageParser):
    """Parser for product gallery images."""
    
    def parse(self, output_dir: str, hero_url: Optional[str] = None) -> List[str]:
        """
        Parse product gallery images from ImageBlockATF JavaScript block.
        Fast DOM-based extraction without clicks.
        
        Args:
            output_dir: Directory to save images
            hero_url: Hero image URL to exclude from gallery
            
        Returns:
            List of saved image paths
        """
        saved_images = []
        driver = self.browser.get_driver()
        
        logger.info("Parsing gallery images from ImageBlockATF JavaScript block...")
        
        # Try to extract from ImageBlockATF script block
        all_urls = self._extract_from_image_block_atf(driver)
        
        if not all_urls:
            logger.warning("⚠ Could not extract from ImageBlockATF, trying fallback method...")
            all_urls = self._extract_from_dom_fallback(driver, hero_url)
        
        # Remove hero image if provided
        hero_url_normalized = None
        if hero_url:
            hero_url_normalized = self._normalize_url_for_comparison(hero_url)
        
        gallery_urls = []
        for url in all_urls:
            if not url or not url.startswith('http'):
                continue
            
            if is_excluded_url(url):
                continue
            
            # Check if it's hero image
            is_hero = False
            if hero_url_normalized:
                url_normalized = self._normalize_url_for_comparison(url)
                if hero_url_normalized == url_normalized:
                    is_hero = True
                    logger.debug(f"  ✗ Skipped hero duplicate: {url[:60]}...")
            
            if not is_hero and url not in gallery_urls:
                gallery_urls.append(url)
                logger.info(f"  ✓ Added gallery URL: {url[:60]}...")
        
        # Save images
        if not gallery_urls:
            logger.warning("⚠ No gallery images found")
            return saved_images
        
        gallery_dir = Path(output_dir) / 'product'
        gallery_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Downloading {len(gallery_urls)} gallery images...")
        for i, url in enumerate(gallery_urls, 1):
            try:
                output_path = gallery_dir / f'product{i}.jpg'
                logger.info(f"  [Download {i}/{len(gallery_urls)}] Downloading product{i}.jpg...")
                logger.debug(f"  [Download {i}/{len(gallery_urls)}] URL: {url[:80]}...")
                
                if save_image_with_dedup(url, str(output_path), self.md5_cache):
                    saved_images.append(str(output_path))
                    logger.info(f"  [Download {i}/{len(gallery_urls)}] ✓ Saved: product{i}.jpg")
                else:
                    logger.warning(f"  [Download {i}/{len(gallery_urls)}] ✗ Failed to save")
            except Exception as e:
                logger.error(f"  [Download {i}/{len(gallery_urls)}] ✗ Exception: {e}")
                import traceback
                logger.debug(traceback.format_exc())
        
        logger.info(f"✓ Gallery parsing complete: {len(saved_images)} images saved")
        return saved_images
    
    def _extract_from_image_block_atf(self, driver) -> List[str]:
        """
        Extract image URLs from ImageBlockATF JavaScript block.
        
        Structure:
        P.when('A').register("ImageBlockATF", function(A){
          var data = {
            'colorImages': {
              'initial': [
                {
                  'hiRes': 'url1',
                  'main': {'url': [width, height], ...}
                },
                ...
              ]
            }
          };
        });
        
        Returns:
            List of image URLs (first is hero, rest are gallery)
        """
        all_urls = []
        
        try:
            # Find script tag with ImageBlockATF
            scripts = driver.find_elements(By.TAG_NAME, 'script')
            logger.info(f"Found {len(scripts)} script tags, searching for ImageBlockATF...")
            
            for script in scripts:
                try:
                    script_text = script.get_attribute('innerHTML') or script.get_attribute('textContent') or ''
                    
                    # Check if this is ImageBlockATF script
                    if 'ImageBlockATF' not in script_text or 'colorImages' not in script_text:
                        continue
                    
                    logger.info("✓ Found ImageBlockATF script block!")
                    
                    # Extract data object using regex
                    # Look for: var data = { ... };
                    data_match = re.search(r'var\s+data\s*=\s*({[^}]+(?:{[^}]+}[^}]*)*})', script_text, re.DOTALL)
                    if not data_match:
                        # Try alternative pattern
                        data_match = re.search(r"'colorImages':\s*({[^}]+(?:{[^}]+}[^}]*)*})", script_text, re.DOTALL)
                    
                    if data_match:
                        data_str = data_match.group(1)
                        logger.debug(f"Extracted data object (first 200 chars): {data_str[:200]}...")
                        
                        # Try to parse as JSON (may need cleanup)
                        try:
                            # Clean up JavaScript object to make it valid JSON
                            # Replace single quotes with double quotes
                            json_str = data_str.replace("'", '"')
                            # Fix unquoted keys
                            json_str = re.sub(r'(\w+):', r'"\1":', json_str)
                            data = json.loads(json_str)
                            
                            # Extract colorImages.initial array
                            if 'colorImages' in data and 'initial' in data['colorImages']:
                                images = data['colorImages']['initial']
                                logger.info(f"Found {len(images)} images in colorImages.initial")
                                
                                for idx, img_data in enumerate(images, 1):
                                    url = None
                                    
                                    # Priority 1: hiRes
                                    if 'hiRes' in img_data and img_data['hiRes']:
                                        url = img_data['hiRes']
                                        logger.debug(f"  Image {idx}: Using hiRes URL")
                                    
                                    # Priority 2: largest from main object
                                    elif 'main' in img_data and isinstance(img_data['main'], dict):
                                        # Find largest size (width * height)
                                        largest_url = None
                                        largest_size = 0
                                        for img_url, size in img_data['main'].items():
                                            if isinstance(size, list) and len(size) >= 2:
                                                img_size = size[0] * size[1]
                                                if img_size > largest_size:
                                                    largest_size = img_size
                                                    largest_url = img_url
                                        if largest_url:
                                            url = largest_url
                                            logger.debug(f"  Image {idx}: Using largest from main ({largest_size}px)")
                                    
                                    # Priority 3: large
                                    elif 'large' in img_data and img_data['large']:
                                        url = img_data['large']
                                        logger.debug(f"  Image {idx}: Using large URL")
                                    
                                    if url:
                                        # Convert to high-res
                                        url = get_high_res_url(url)
                                        all_urls.append(url)
                                        logger.info(f"  Image {idx}: {url[:60]}...")
                                
                                if all_urls:
                                    logger.info(f"✓ Extracted {len(all_urls)} URLs from ImageBlockATF")
                                    # Skip first image (hero), return rest
                                    return all_urls[1:] if len(all_urls) > 1 else []
                        except json.JSONDecodeError as e:
                            logger.debug(f"JSON parse error: {e}, trying regex extraction...")
                            # Fallback: extract URLs directly with regex
                            urls = self._extract_urls_from_script_regex(script_text)
                            if urls:
                                logger.info(f"✓ Extracted {len(urls)} URLs using regex")
                                return urls[1:] if len(urls) > 1 else []
                        except Exception as e:
                            logger.debug(f"Error parsing ImageBlockATF: {e}")
                            continue
                    
                except Exception as e:
                    logger.debug(f"Error processing script: {e}")
                    continue
            
            logger.warning("⚠ ImageBlockATF script block not found")
            
        except Exception as e:
            logger.error(f"Error extracting from ImageBlockATF: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        
        return []
    
    def _extract_urls_from_script_regex(self, script_text: str) -> List[str]:
        """Extract image URLs from script text using regex."""
        urls = []
        
        # Look for hiRes URLs
        hi_res_pattern = r'"hiRes"\s*:\s*"([^"]+)"'
        hi_res_matches = re.findall(hi_res_pattern, script_text)
        if hi_res_matches:
            urls.extend(hi_res_matches)
            logger.debug(f"Found {len(hi_res_matches)} hiRes URLs via regex")
        
        # If no hiRes, look for main object URLs
        if not urls:
            # Pattern: "url": [width, height]
            main_pattern = r'"https://[^"]+\.jpg[^"]*"\s*:\s*\[\d+,\d+\]'
            main_matches = re.findall(main_pattern, script_text)
            if main_matches:
                # Extract URLs from matches
                url_pattern = r'(https://[^"]+\.jpg[^"]*)'
                for match in main_matches:
                    url_match = re.search(url_pattern, match)
                    if url_match:
                        urls.append(url_match.group(1))
                logger.debug(f"Found {len(urls)} main URLs via regex")
        
        # Remove duplicates and convert to high-res
        unique_urls = []
        seen = set()
        for url in urls:
            if url not in seen:
                seen.add(url)
                high_res_url = get_high_res_url(url)
                unique_urls.append(high_res_url)
        
        return unique_urls
    
    def _extract_from_dom_fallback(self, driver, hero_url: Optional[str]) -> List[str]:
        """Fallback method: extract from DOM if ImageBlockATF not available."""
        logger.info("Using fallback DOM extraction method...")
        all_urls = []
        hero_url_normalized = None
        if hero_url:
            hero_url_normalized = self._normalize_url_for_comparison(hero_url)
        
        # Scroll to gallery
        try:
            gallery_container = driver.find_element(By.CSS_SELECTOR, '#altImages, #imageBlock_feature_div')
            self.browser.scroll_to_element(gallery_container)
            # No delay needed - scroll_to_element now waits for element visibility
        except:
            pass
        
        # Try to find li.item containers and extract from them
        thumbnail_selectors = [
            '#altImages ul li.item',
            '#altImages li',
        ]
        
        thumbnails = []
        for selector in thumbnail_selectors:
            try:
                found = driver.find_elements(By.CSS_SELECTOR, selector)
                if found:
                    thumbnails = found
                    logger.info(f"Found {len(thumbnails)} thumbnail containers")
                    break
            except:
                continue
        
        if not thumbnails:
            return []
        
        # Extract URLs from containers (no clicks)
        for idx, thumb in enumerate(thumbnails, 1):
            try:
                # Skip video thumbnails
                try:
                    img = thumb.find_element(By.CSS_SELECTOR, 'img')
                    if self._is_video_thumbnail(img):
                        continue
                except:
                    pass
                
                # Try to extract URL from container or img
                url = None
                
                # Check container first
                json_data = thumb.get_attribute('data-a-dynamic-image')
                if json_data:
                    url = self._extract_url_from_json(json_data)
                
                # Check img if container didn't work
                if not url:
                    try:
                        img = thumb.find_element(By.CSS_SELECTOR, 'img')
                        url = self._extract_high_res_url_from_element(img)
                    except:
                        pass
                
                if url and url.startswith('http') and not is_excluded_url(url):
                    # Check if hero duplicate
                    is_hero = False
                    if hero_url_normalized:
                        url_normalized = self._normalize_url_for_comparison(url)
                        if hero_url_normalized == url_normalized:
                            is_hero = True
                    
                    if not is_hero and url not in all_urls:
                        all_urls.append(url)
                        logger.debug(f"  [Thumbnail {idx}] ✓ Added: {url[:60]}...")
                        
            except Exception as e:
                logger.debug(f"  [Thumbnail {idx}] Error: {e}")
                continue
        
        return all_urls
        
        # Save images
        if not all_urls:
            logger.warning("⚠ No gallery images found")
            return saved_images
        
        gallery_dir = Path(output_dir) / 'product'
        gallery_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Downloading {len(all_urls)} gallery images...")
        for i, url in enumerate(all_urls, 1):
            try:
                output_path = gallery_dir / f'product{i}.jpg'
                logger.info(f"  [Download {i}/{len(all_urls)}] Downloading product{i}.jpg...")
                logger.debug(f"  [Download {i}/{len(all_urls)}] URL: {url[:80]}...")
                
                if save_image_with_dedup(url, str(output_path), self.md5_cache):
                    saved_images.append(str(output_path))
                    logger.info(f"  [Download {i}/{len(all_urls)}] ✓ Saved: product{i}.jpg")
                else:
                    logger.warning(f"  [Download {i}/{len(all_urls)}] ✗ Failed to save (check logs above for reason)")
            except Exception as e:
                logger.error(f"  [Download {i}/{len(all_urls)}] ✗ Exception: {e}")
                import traceback
                logger.debug(traceback.format_exc())
        
        logger.info(f"✓ Gallery parsing complete: {len(saved_images)} images saved")
        return saved_images

