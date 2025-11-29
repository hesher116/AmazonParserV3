"""A+ Brand Parser - Parses A+ Brand Story images"""
from typing import List, Optional, Dict
from pathlib import Path
import time

from selenium.webdriver.common.by import By

from agents.base_image_parser import BaseImageParser
from utils.file_utils import save_image_with_dedup, is_excluded_url, get_high_res_url
from utils.logger import get_logger

logger = get_logger(__name__)


class APlusBrandParser(BaseImageParser):
    """Parser for A+ Brand Story images."""
    
    def __init__(self, browser_pool, md5_cache):
        super().__init__(browser_pool, md5_cache)
        self._image_alt_texts = {}  # Store alt text for each URL
    
    def parse(self, output_dir: str) -> Dict:
        """
        Parse A+ Brand Story images.
        
        Args:
            output_dir: Directory to save images
            
        Returns:
            Dict with 'images' (list of paths) and 'alt_texts' (dict mapping path to alt text)
        """
        saved_images = []
        aplus_dir = Path(output_dir) / 'aplus_brand'
        section_markers = ['From the brand', 'From the Brand']
        filename_prefix = 'brand'
        
        driver = self.browser.get_driver()
        
        # Quick check: if there's no h2 heading "From the brand", skip parsing
        try:
            h2_elements = driver.find_elements(By.CSS_SELECTOR, 'h2')
            has_brand_heading = False
            for h2 in h2_elements:
                h2_text = h2.text.strip().upper() if h2.text else ''
                if 'FROM THE BRAND' in h2_text:
                    has_brand_heading = True
                    logger.info(f"Found h2 heading: {h2.text[:50]}")
                    break
            
            if not has_brand_heading:
                logger.info(f"No 'From the brand' heading found, skipping A+ brand parsing")
                return {
                    'images': [],
                    'alt_texts': {}
                }
        except Exception as e:
            logger.debug(f"Error checking for h2 heading: {e}")
        
        # Find A+ content sections - optimized search
        logger.info(f"Searching for A+ brand sections...")
        search_start = time.time()
        
        # Specific selectors for brand story
        specific_selectors = [
            '#aplusBrandStory_feature_div',
            '[data-feature-name="aplusBrandStory"]',
        ]
        
        # General A+ selectors
        general_selectors = [
            '#aplus_feature_div',
            '#aplus',
            '.aplus-module',
            '[data-feature-name="aplus"]',
        ]
        
        all_selectors = specific_selectors + general_selectors
        logger.info(f"  [A+ brand] Checking {len(all_selectors)} selectors")
        
        # Limit search time
        max_selector_checks = 3
        sections_found = False
        
        for idx, selector in enumerate(all_selectors):
            try:
                selector_start = time.time()
                logger.info(f"  [A+ brand] Checking selector {idx + 1}/{len(all_selectors)}: {selector}")
                sections = driver.find_elements(By.CSS_SELECTOR, selector)
                selector_time = time.time() - selector_start
                
                if not sections:
                    logger.debug(f"  [A+ brand] Selector '{selector}' found 0 sections ({selector_time:.2f}s)")
                    if idx >= max_selector_checks and not sections_found:
                        total_time = time.time() - search_start
                        logger.info(f"  [A+ brand] No sections found after checking {idx + 1} selectors ({total_time:.2f}s), skipping...")
                        return saved_images
                    continue
                
                logger.info(f"  [A+ brand] Selector '{selector}' found {len(sections)} sections ({selector_time:.2f}s)")
                sections_found = True
                
                for section in sections:
                    try:
                        # Quick check
                        is_target_section = False
                        
                        if selector in specific_selectors:
                            is_target_section = True
                        else:
                            try:
                                section_text = section.text[:200] if section.text else ''
                                section_text = section_text.upper()
                                is_target_section = any(marker.upper() in section_text for marker in section_markers)
                            except:
                                continue
                        
                        if not is_target_section:
                            logger.debug(f"Skipping section - doesn't match brand")
                            continue
                        
                        logger.info(f"Found target section for brand, extracting images...")
                        
                        # Quick check for images first (before scrolling)
                        images = section.find_elements(By.CSS_SELECTOR, 'img')
                        if not images:
                            logger.warning(f"  [A+ brand] No img tags found in section, skipping...")
                            continue
                        
                        logger.info(f"  [A+ brand] Found {len(images)} img tags in section (including carousel)")
                        
                        # No scroll needed - images are already in DOM dump, we're parsing from static HTML
                        
                        # Process images and group by type (regular vs carousel)
                        image_items = []  # List of dicts: {url, alt_text, is_carousel, img_element}
                        
                        for img in images:
                            # Check if image is in carousel
                            is_carousel = self._is_in_carousel(img)
                            
                            # Extract alt text
                            alt_text = img.get_attribute('alt') or ''
                            
                            # Extract URL
                            url = self._extract_aplus_url_from_element(img)
                            
                            if not url or not url.startswith('http'):
                                continue
                            
                            if is_excluded_url(url):
                                continue
                            
                            # Check if we already have this URL
                            existing = next((item for item in image_items if item['url'] == url), None)
                            if existing:
                                continue
                            
                            image_items.append({
                                'url': url,
                                'alt_text': alt_text,
                                'is_carousel': is_carousel,
                                'img_element': img  # Keep reference for carousel grouping
                            })
                        
                        # Save images in DOM order (as they appear on the page)
                        if image_items:
                            aplus_dir.mkdir(parents=True, exist_ok=True)
                            logger.info(f"Found {len(image_items)} images, saving in DOM order...")
                            
                            file_counter = 1
                            processed_indices = set()  # Track which images we've already processed
                            
                            # Process images in DOM order
                            for idx, img_data in enumerate(image_items):
                                if idx in processed_indices:
                                    continue  # Already processed as part of a carousel
                                
                                if img_data['is_carousel']:
                                    # Find all consecutive images from the same carousel
                                    carousel_id = self._get_carousel_id(img_data['img_element'])
                                    carousel_items = [img_data]
                                    
                                    # Collect all consecutive images from the same carousel
                                    for next_idx in range(idx + 1, len(image_items)):
                                        next_img = image_items[next_idx]
                                        if next_img['is_carousel']:
                                            next_carousel_id = self._get_carousel_id(next_img['img_element'])
                                            if next_carousel_id == carousel_id:
                                                carousel_items.append(next_img)
                                                processed_indices.add(next_idx)
                                            else:
                                                break  # Different carousel, stop
                                        else:
                                            break  # Regular image, stop
                                    
                                    # Save carousel images
                                    base_number = file_counter
                                    for carousel_idx, item in enumerate(carousel_items, 1):
                                        output_path = aplus_dir / f'{filename_prefix}{base_number}.{carousel_idx}(CAROUSEL).jpg'
                                        if save_image_with_dedup(item['url'], str(output_path), self.md5_cache):
                                            saved_images.append(str(output_path))
                                            if item['alt_text']:
                                                self._image_alt_texts[str(output_path)] = item['alt_text']
                                                self._image_alt_texts[str(output_path.resolve())] = item['alt_text']
                                                self._image_alt_texts[output_path.name] = item['alt_text']
                                                self._image_alt_texts[f"aplus_brand/{output_path.name}"] = item['alt_text']
                                            logger.info(f"  [A+ brand] ✓ Saved: {filename_prefix}{base_number}.{carousel_idx}(CAROUSEL).jpg")
                                    file_counter += 1
                                else:
                                    # Save regular image
                                    output_path = aplus_dir / f'{filename_prefix}{file_counter}.jpg'
                                    if save_image_with_dedup(img_data['url'], str(output_path), self.md5_cache):
                                        saved_images.append(str(output_path))
                                        if img_data['alt_text']:
                                            self._image_alt_texts[str(output_path)] = img_data['alt_text']
                                            self._image_alt_texts[str(output_path.resolve())] = img_data['alt_text']
                                            self._image_alt_texts[output_path.name] = img_data['alt_text']
                                            self._image_alt_texts[f"aplus_brand/{output_path.name}"] = img_data['alt_text']
                                        logger.info(f"  [A+ brand] ✓ Saved: {filename_prefix}{file_counter}.jpg")
                                        file_counter += 1
                            
                            logger.info(f"Saved {len(saved_images)}/{len(image_items)} brand images, moving on...")
                            break
                            
                    except Exception as e:
                        logger.debug(f"Error processing section: {e}")
                        continue
                
                if saved_images:
                    break
                    
            except Exception as e:
                logger.debug(f"A+ selector {selector} failed: {e}")
                continue
        
        logger.info(f"A+ brand images saved: {len(saved_images)}")
        # Return dict with images and alt texts
        return {
            'images': saved_images,
            'alt_texts': {path: self._image_alt_texts.get(path, '') for path in saved_images}
        }
    
    def _extract_aplus_url_from_element(self, element) -> Optional[str]:
        """
        Extract URL from A+ content image element.
        For A+ images, use URL as-is (don't apply get_high_res_url transformation).
        
        Priority:
        1. data-src (often used for lazy loading in A+)
        2. src (direct URL)
        3. data-old-hires (if present)
        
        Args:
            element: Selenium WebElement with image
            
        Returns:
            Image URL as-is (for A+ content)
        """
        # Priority 1: data-src (often used in A+ content)
        url = element.get_attribute('data-src')
        if url and url.startswith('http'):
            return url
        
        # Priority 2: src (direct URL)
        url = element.get_attribute('src')
        if url and url.startswith('http'):
            return url
        
        # Priority 3: data-old-hires (if present)
        url = element.get_attribute('data-old-hires')
        if url and url.startswith('http'):
            return url
        
        # Check parent element
        try:
            parent = element.find_element(By.XPATH, './..')
            url = parent.get_attribute('data-src') or parent.get_attribute('data-old-hires')
            if url and url.startswith('http'):
                return url
        except:
            pass
        
        return None
    
    def _is_in_carousel(self, img_element) -> bool:
        """Check if image element is inside a carousel."""
        try:
            # Check parent elements for carousel indicators
            current = img_element
            for _ in range(10):  # Check up to 10 levels up
                try:
                    parent = current.find_element(By.XPATH, './..')
                    parent_class = parent.get_attribute('class') or ''
                    parent_id = parent.get_attribute('id') or ''
                    
                    # Check for carousel indicators
                    if any(indicator in parent_class.lower() for indicator in [
                        'carousel', 'a-carousel', 'aplus-carousel'
                    ]):
                        return True
                    
                    if 'carousel' in parent_id.lower():
                        return True
                    
                    # Check for carousel role
                    role = parent.get_attribute('role') or ''
                    if 'carousel' in role.lower():
                        return True
                    
                    current = parent
                except:
                    break
        except:
            pass
        
        return False
    
    def _get_carousel_id(self, img_element) -> str:
        """Get carousel container ID for grouping carousel images."""
        try:
            current = img_element
            for _ in range(10):  # Check up to 10 levels up
                try:
                    parent = current.find_element(By.XPATH, './..')
                    parent_id = parent.get_attribute('id') or ''
                    parent_class = parent.get_attribute('class') or ''
                    
                    # If we find a carousel container with ID
                    if 'carousel' in parent_class.lower() and parent_id:
                        return parent_id
                    
                    # Check for carousel role
                    role = parent.get_attribute('role') or ''
                    if 'carousel' in role.lower() and parent_id:
                        return parent_id
                    
                    current = parent
                except:
                    break
        except:
            pass
        
        # Fallback: use a default ID if no specific carousel found
        return 'default_carousel'

