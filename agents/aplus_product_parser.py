"""A+ Product Parser - Parses A+ Product Description images"""
from typing import List, Optional, Dict
from pathlib import Path
import time

from selenium.webdriver.common.by import By

from agents.base_image_parser import BaseImageParser
from utils.file_utils import save_image_with_dedup, is_excluded_url, get_high_res_url
from utils.logger import get_logger

logger = get_logger(__name__)


class APlusProductParser(BaseImageParser):
    """Parser for A+ Product Description images."""
    
    def __init__(self, browser_pool, md5_cache):
        super().__init__(browser_pool, md5_cache)
        self._image_alt_texts = {}  # Store alt text for each URL
    
    def parse(self, output_dir: str) -> List[str]:
        """
        Parse A+ Product Description images.
        
        Args:
            output_dir: Directory to save images
            
        Returns:
            List of saved image paths
        """
        saved_images = []
        aplus_dir = Path(output_dir) / 'aplus_product'
        section_markers = ['Product description', 'Product Description']
        filename_prefix = 'A+'
        
        driver = self.browser.get_driver()
        
        # Quick check: if there's no h2 heading "Product description", skip parsing
        try:
            h2_elements = driver.find_elements(By.CSS_SELECTOR, 'h2')
            has_product_heading = False
            for h2 in h2_elements:
                h2_text = h2.text.strip().upper() if h2.text else ''
                if 'PRODUCT DESCRIPTION' in h2_text:
                    has_product_heading = True
                    logger.info(f"Found h2 heading: {h2.text[:50]}")
                    break
            
            if not has_product_heading:
                logger.info(f"No 'Product description' heading found, skipping A+ product parsing")
                return {
                    'images': [],
                    'alt_texts': {}
                }
        except Exception as e:
            logger.debug(f"Error checking for h2 heading: {e}")
        
        # Find A+ content sections - optimized search
        logger.info(f"Searching for A+ product sections...")
        search_start = time.time()
        
        # Specific selectors for product description
        specific_selectors = [
            '#productDescription_feature_div',
            '[data-feature-name="productDescription"]',
        ]
        
        # General A+ selectors
        general_selectors = [
            '#aplus_feature_div',
            '#aplus',
            '.aplus-module',
            '[data-feature-name="aplus"]',
        ]
        
        all_selectors = specific_selectors + general_selectors
        logger.info(f"  [A+ product] Checking {len(all_selectors)} selectors")
        
        for idx, selector in enumerate(all_selectors):
            try:
                selector_start = time.time()
                logger.info(f"  [A+ product] Checking selector {idx + 1}/{len(all_selectors)}: {selector}")
                sections = driver.find_elements(By.CSS_SELECTOR, selector)
                selector_time = time.time() - selector_start
                
                if not sections:
                    logger.debug(f"  [A+ product] Selector '{selector}' found 0 sections ({selector_time:.2f}s)")
                    # Skip immediately if no sections found - no need to wait
                    continue
                
                logger.info(f"  [A+ product] Selector '{selector}' found {len(sections)} sections ({selector_time:.2f}s)")
                
                for section in sections:
                    try:
                        # Quick check: if selector is specific, assume it matches
                        is_target_section = False
                        
                        if selector in specific_selectors:
                            is_target_section = True
                        else:
                            # For general selectors, do quick text check
                            try:
                                section_text = section.text[:200] if section.text else ''
                                section_text = section_text.upper()
                                is_target_section = any(marker.upper() in section_text for marker in section_markers)
                            except:
                                continue
                        
                        if not is_target_section:
                            logger.debug(f"Skipping section - doesn't match product")
                            continue
                        
                        logger.info(f"Found target section for product, extracting images...")
                        
                        # Quick check for images first (before scrolling)
                        images = section.find_elements(By.CSS_SELECTOR, 'img')
                        if not images:
                            logger.warning(f"  [A+ product] No img tags found in section, skipping...")
                            continue
                        
                        logger.info(f"  [A+ product] Found {len(images)} img tags in section (including carousel)")
                        
                        # No scroll needed - images are already in DOM dump, we're parsing from static HTML
                        
                        # Group images: regular and carousel
                        image_data = []  # List of dicts: {url, alt_text, is_carousel, carousel_index}
                        
                        for img_idx, img in enumerate(images, 1):
                            try:
                                # Extract alt text
                                alt_text = img.get_attribute('alt') or ''
                                
                                # Extract URL
                                url = self._extract_aplus_url_from_element(img)
                                
                                # Log all attributes for debugging (only first 3 images to reduce spam)
                                if img_idx <= 3:
                                    src_attr = img.get_attribute('src') or ''
                                    data_src_attr = img.get_attribute('data-src') or ''
                                    data_old_hires_attr = img.get_attribute('data-old-hires') or ''
                                    logger.info(f"  [A+ product] Image {img_idx}: src='{src_attr[:60]}...' data-src='{data_src_attr[:60]}...' data-old-hires='{data_old_hires_attr[:60]}...'")
                                
                                if not url:
                                    if img_idx <= 3:
                                        logger.warning(f"  [A+ product] Image {img_idx}: Could not extract URL from any attribute")
                                    continue
                                
                                logger.info(f"  [A+ product] Image {img_idx}/{len(images)}: Extracted URL: {url[:80]}...")
                                
                                if not url.startswith('http'):
                                    logger.warning(f"  [A+ product] Image {img_idx}/{len(images)}: Invalid URL (not http): {url[:60]}...")
                                    continue
                                
                                if is_excluded_url(url):
                                    logger.warning(f"  [A+ product] Image {img_idx}/{len(images)}: Excluded URL: {url[:60]}...")
                                    continue
                                
                                # Check if we already have this URL
                                existing = next((item for item in image_data if item['url'] == url), None)
                                if existing:
                                    if img_idx <= 3:
                                        logger.info(f"  [A+ product] Image {img_idx}: Duplicate URL skipped")
                                    continue
                                
                                # Check if image is in carousel
                                is_carousel = self._is_in_carousel(img)
                                
                                image_data.append({
                                    'url': url,
                                    'alt_text': alt_text,
                                    'is_carousel': is_carousel,
                                    'img_element': img  # Keep reference for carousel grouping
                                })
                                logger.info(f"  [A+ product] Image {img_idx}/{len(images)}: ✓ Added URL (carousel: {is_carousel}, alt: '{alt_text[:30] if alt_text else 'no alt'}')")
                            except Exception as img_error:
                                logger.error(f"  [A+ product] Image {img_idx}/{len(images)}: Error processing image: {img_error}", exc_info=True)
                                continue
                        
                        logger.info(f"  [A+ product] Extracted {len(image_data)} valid image URLs from {len(images)} img tags")
                        
                        # Save images in DOM order (as they appear on the page)
                        if image_data:
                            aplus_dir.mkdir(parents=True, exist_ok=True)
                            logger.info(f"Found {len(image_data)} images, saving in DOM order...")
                            
                            file_counter = 1
                            processed_indices = set()  # Track which images we've already processed
                            
                            # Process images in DOM order
                            for idx, img_data in enumerate(image_data):
                                if idx in processed_indices:
                                    continue  # Already processed as part of a carousel
                                
                                if img_data['is_carousel']:
                                    # Find all consecutive images from the same carousel
                                    carousel_id = self._get_carousel_id(img_data['img_element'])
                                    carousel_items = [img_data]
                                    
                                    # Collect all consecutive images from the same carousel
                                    for next_idx in range(idx + 1, len(image_data)):
                                        next_img = image_data[next_idx]
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
                                        logger.debug(f"  [A+ product] Attempting to save carousel: {output_path.name} from URL: {item['url'][:60]}...")
                                        if save_image_with_dedup(item['url'], str(output_path), self.md5_cache):
                                            saved_images.append(str(output_path))
                                            # Store alt text with multiple path formats for lookup
                                            if item['alt_text']:
                                                self._image_alt_texts[str(output_path)] = item['alt_text']
                                                self._image_alt_texts[str(output_path.resolve())] = item['alt_text']
                                                self._image_alt_texts[output_path.name] = item['alt_text']
                                                self._image_alt_texts[f"aplus_product/{output_path.name}"] = item['alt_text']
                                            logger.info(f"  [A+ product] ✓ Saved: {filename_prefix}{base_number}.{carousel_idx}(CAROUSEL).jpg")
                                        else:
                                            logger.warning(f"  [A+ product] ✗ Failed to save carousel: {filename_prefix}{base_number}.{carousel_idx}(CAROUSEL).jpg")
                                    file_counter += 1
                                else:
                                    # Save regular image
                                    output_path = aplus_dir / f'{filename_prefix}{file_counter}.jpg'
                                    logger.debug(f"  [A+ product] Attempting to save: {output_path.name} from URL: {img_data['url'][:60]}...")
                                    if save_image_with_dedup(img_data['url'], str(output_path), self.md5_cache):
                                        saved_images.append(str(output_path))
                                        # Store alt text with multiple path formats for lookup
                                        if img_data['alt_text']:
                                            self._image_alt_texts[str(output_path)] = img_data['alt_text']
                                            self._image_alt_texts[str(output_path.resolve())] = img_data['alt_text']
                                            self._image_alt_texts[output_path.name] = img_data['alt_text']
                                            self._image_alt_texts[f"aplus_product/{output_path.name}"] = img_data['alt_text']
                                        logger.info(f"  [A+ product] ✓ Saved: {filename_prefix}{file_counter}.jpg")
                                        file_counter += 1
                                    else:
                                        logger.warning(f"  [A+ product] ✗ Failed to save: {filename_prefix}{file_counter}.jpg")
                            
                            logger.info(f"Saved {len(saved_images)}/{len(image_data)} product images, moving on...")
                            break
                        else:
                            logger.warning(f"  [A+ product] No image data extracted from {len(images)} img tags")
                            
                    except Exception as e:
                        logger.debug(f"Error processing section: {e}")
                        continue
                
                if saved_images:
                    break
                    
            except Exception as e:
                logger.debug(f"A+ selector {selector} failed: {e}")
                continue
        
        logger.info(f"A+ product images saved: {len(saved_images)}")
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
        4. Check parent element for data attributes
        5. Check for data-a-dynamic-image (JSON format)
        
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
        
        # Priority 4: data-a-dynamic-image (JSON format, extract largest)
        data_dynamic = element.get_attribute('data-a-dynamic-image')
        if data_dynamic:
            try:
                import json
                dynamic_data = json.loads(data_dynamic)
                if isinstance(dynamic_data, dict):
                    # Get the largest image URL
                    largest_url = None
                    largest_size = 0
                    for img_url, sizes in dynamic_data.items():
                        if isinstance(sizes, list) and len(sizes) >= 2:
                            size = sizes[0] * sizes[1]
                            if size > largest_size:
                                largest_size = size
                                largest_url = img_url
                    if largest_url and largest_url.startswith('http'):
                        return largest_url
            except:
                pass
        
        # Priority 5: Check parent element for data attributes
        try:
            parent = element.find_element(By.XPATH, './..')
            url = parent.get_attribute('data-src') or parent.get_attribute('data-old-hires')
            if url and url.startswith('http'):
                return url
        except:
            pass
        
        return None
    
    def _is_in_carousel(self, element) -> bool:
        """Check if image element is inside a carousel."""
        try:
            current = element
            for _ in range(10):  # Check up to 10 levels up
                try:
                    parent = current.find_element(By.XPATH, './..')
                    parent_class = parent.get_attribute('class') or ''
                    parent_role = parent.get_attribute('role') or ''
                    
                    # Check for carousel indicators
                    if 'carousel' in parent_class.lower() or 'carousel' in parent_role.lower():
                        return True
                    
                    # Check for common carousel patterns
                    if 'a-carousel' in parent_class.lower():
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
    
    def _parse_carousel_in_section(self, section) -> List[str]:
        """Parse carousel images within a section."""
        urls = []
        driver = self.browser.get_driver()
        
        try:
            # Quick check: if no images in section, skip carousel parsing immediately
            initial_images = section.find_elements(By.TAG_NAME, 'img')
            if not initial_images:
                return urls
            
            next_buttons = section.find_elements(
                By.CSS_SELECTOR, 
                '.a-carousel-goto-nextpage, [aria-label="Next"], .a-carousel-right'
            )
            
            if not next_buttons:
                return urls
            
            # Get initial images (reuse the check we already did)
            visible_images = initial_images
            for img in visible_images:
                url = self._extract_aplus_url_from_element(img)
                if url and not is_excluded_url(url) and url.startswith('http'):
                    if url not in urls:
                        urls.append(url)
                        # Store alt text
                        alt_text = img.get_attribute('alt') or ''
                        if alt_text:
                            self._image_alt_texts[url] = alt_text
            
            # Click through carousel until duplicate
            seen_urls = set(urls)
            max_clicks = 20
            
            for click_num in range(max_clicks):
                try:
                    found_new = False
                    for btn in next_buttons:
                        if btn.is_displayed() and btn.is_enabled():
                            self.browser.click_element(btn)
                            self.browser._random_sleep(0.15, 0.25)
                            
                            new_images = section.find_elements(By.TAG_NAME, 'img')
                            for img in new_images:
                                url = self._extract_aplus_url_from_element(img)
                                if url and not is_excluded_url(url) and url.startswith('http'):
                                    if url in seen_urls:
                                        return urls
                                    
                                    seen_urls.add(url)
                                    urls.append(url)
                                    # Store alt text
                                    alt_text = img.get_attribute('alt') or ''
                                    if alt_text:
                                        self._image_alt_texts[url] = alt_text
                                    found_new = True
                            
                            if not found_new:
                                return urls
                            break
                    
                    if not found_new:
                        break
                except Exception:
                    break
                    
        except Exception as e:
            logger.debug(f"Carousel parsing failed: {e}")
        
        return urls

