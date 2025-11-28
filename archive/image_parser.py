"""Image Parser Agent - Parses hero, gallery, and A+ content images"""
import os
import re
import json
from typing import Dict, List, Set, Optional
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from core.browser_pool import BrowserPool
from utils.file_utils import save_image_with_dedup, get_high_res_url, is_excluded_url, download_image, calculate_md5
from utils.logger import get_logger
from config.settings import Settings

logger = get_logger(__name__)


class ImageParserAgent:
    """Agent for parsing product images from Amazon."""
    
    def __init__(self, browser_pool: BrowserPool):
        self.browser = browser_pool
        self.md5_cache: Set[str] = set()
    
    def parse(self, output_dir: str) -> Dict:
        """
        Parse all images from the current page.
        
        Args:
            output_dir: Directory to save images
            
        Returns:
            Dictionary with parsing results
        """
        logger.info("=" * 60)
        logger.info("Starting image parsing...")
        logger.info(f"Output directory: {output_dir}")
        
        results = {
            'hero': [],
            'gallery': [],
            'aplus_brand': [],
            'aplus_product': [],
            'total_images': 0,
            'errors': []
        }
        
        try:
            # Parse hero image
            logger.info("-" * 60)
            logger.info("Step 1: Parsing hero image...")
            hero_images, hero_url = self.parse_hero_image(output_dir)
            results['hero'] = hero_images
            logger.info(f"Hero images found: {len(hero_images)}")
            
            # Parse gallery images (exclude hero)
            logger.info("-" * 60)
            logger.info("Step 2: Parsing gallery images...")
            gallery_images = self.parse_gallery_images(output_dir, hero_url=hero_url)
            results['gallery'] = gallery_images
            logger.info(f"Gallery images found: {len(gallery_images)}")
            
            # Parse A+ content images
            logger.info("-" * 60)
            logger.info("Step 3: Parsing A+ brand images...")
            aplus_brand = self.parse_aplus_images(output_dir, 'brand')
            results['aplus_brand'] = aplus_brand
            logger.info(f"A+ brand images found: {len(aplus_brand)}")
            
            logger.info("-" * 60)
            logger.info("Step 4: Parsing A+ product images...")
            aplus_product = self.parse_aplus_images(output_dir, 'product')
            results['aplus_product'] = aplus_product
            logger.info(f"A+ product images found: {len(aplus_product)}")
            
            results['total_images'] = (
                len(hero_images) + 
                len(gallery_images) + 
                len(aplus_brand) + 
                len(aplus_product)
            )
            
            logger.info("=" * 60)
            logger.info(f"Image parsing complete: {results['total_images']} total images saved")
            logger.info(f"  - Hero: {len(hero_images)}")
            logger.info(f"  - Gallery: {len(gallery_images)}")
            logger.info(f"  - A+ Brand: {len(aplus_brand)}")
            logger.info(f"  - A+ Product: {len(aplus_product)}")
            logger.info("=" * 60)
            
        except Exception as e:
            import traceback
            logger.error(f"Image parsing error: {e}")
            logger.error(traceback.format_exc())
            results['errors'].append(str(e))
        
        return results
    
    def parse_hero_image(self, output_dir: str) -> List[str]:
        """
        Parse the main hero image.
        
        Args:
            output_dir: Directory to save images
            
        Returns:
            Tuple of (list of saved image paths, hero URL)
        """
        saved_images = []
        hero_url = None
        hero_dir = Path(output_dir) / 'hero'
        
        driver = self.browser.get_driver()
        
        # Selectors for hero image (in order of preference)
        hero_selectors = [
            '#landingImage',
            '#imgBlkFront',
            '#main-image',
            'img[data-old-hires]',
            '#imageBlock img',
            '#main-image-container img',
            '.a-dynamic-image',
        ]
        
        logger.debug(f"Trying {len(hero_selectors)} hero image selectors...")
        
        for i, selector in enumerate(hero_selectors, 1):
            try:
                logger.debug(f"  [{i}/{len(hero_selectors)}] Trying selector: {selector}")
                element = driver.find_element(By.CSS_SELECTOR, selector)
                
                # Use unified extraction method
                url = self._extract_high_res_url_from_element(element)
                
                if url:
                    logger.debug(f"    Found URL: {url[:80]}...")
                    
                    if is_excluded_url(url):
                        logger.debug("    URL excluded (video/360/ad)")
                        continue
                    
                    output_path = hero_dir / 'hero.jpg'
                    logger.info(f"    Saving hero image to: {output_path}")
                    
                    # Create folder only if we're saving
                    hero_dir.mkdir(parents=True, exist_ok=True)
                    hero_url = url  # Store URL for exclusion from gallery
                    if save_image_with_dedup(url, str(output_path), self.md5_cache):
                        saved_images.append(str(output_path))
                        logger.info(f"✓ Hero image saved successfully!")
                        break
                    else:
                        logger.warning("    Failed to save hero image")
                            
            except NoSuchElementException:
                logger.debug(f"    Element not found")
                continue
            except Exception as e:
                logger.debug(f"    Error: {e}")
        
        if not saved_images:
            logger.warning("⚠ No hero image found with any selector")
        
        return saved_images, hero_url
    
    def parse_gallery_images(self, output_dir: str, hero_url: str = None) -> List[str]:
        """
        Parse product gallery images by clicking thumbnails to get full-size URLs.
        Uses clicks to trigger loading of full-size images in main image container.
        
        Args:
            output_dir: Directory to save images
            hero_url: Hero image URL to exclude from gallery
            
        Returns:
            List of saved image paths
        """
        saved_images = []
        driver = self.browser.get_driver()
        
        logger.info("Parsing gallery images by clicking thumbnails...")
        
        # Scroll to gallery
        try:
            gallery_container = driver.find_element(By.CSS_SELECTOR, '#altImages, #imageBlock_feature_div')
            self.browser.scroll_to_element(gallery_container)
            self.browser._random_sleep(0.2, 0.4)
        except:
            pass
        
        # Find all thumbnail buttons/links (not images, but clickable elements)
        thumbnail_selectors = [
            '#altImages ul li.item',  # Thumbnail container (clickable)
            '#altImages li',  # Alternative
        ]
        
        all_urls = []
        hero_url_normalized = None
        if hero_url:
            hero_url_normalized = self._normalize_url_for_comparison(hero_url)
        
        # Try to find thumbnails
        thumbnails = []
        for selector in thumbnail_selectors:
            try:
                found = driver.find_elements(By.CSS_SELECTOR, selector)
                if found:
                    thumbnails = found
                    logger.info(f"Found {len(thumbnails)} thumbnail containers with: {selector}")
                    break
            except:
                continue
        
        if not thumbnails:
            logger.warning("⚠ No gallery thumbnails found")
            return saved_images
        
        # Click each thumbnail and extract URL from main image
        for idx, thumb in enumerate(thumbnails, 1):
            try:
                # Skip video thumbnails
                try:
                    img = thumb.find_element(By.CSS_SELECTOR, 'img')
                    if self._is_video_thumbnail(img):
                        logger.debug(f"  [Thumbnail {idx}/{len(thumbnails)}] Skipped (video)")
                        continue
                except:
                    pass
                
                # Click thumbnail
                try:
                    self.browser.scroll_to_element(thumb)
                    self.browser._random_sleep(0.1, 0.2)
                    thumb.click()
                    self.browser._random_sleep(0.3, 0.5)  # Wait for image to load
                except Exception as e:
                    logger.debug(f"  [Thumbnail {idx}/{len(thumbnails)}] Click failed: {e}")
                    continue
                
                # Extract URL from main image after click
                main_image_selectors = [
                    '#landingImage',
                    '#imgTagWrapperId img',
                    '#main-image-container img',
                ]
                
                url = None
                for img_selector in main_image_selectors:
                    try:
                        main_img = driver.find_element(By.CSS_SELECTOR, img_selector)
                        url = self._extract_high_res_url_from_element(main_img)
                        if url and url.startswith('http') and not is_excluded_url(url):
                            break
                    except:
                        continue
                
                if not url or not url.startswith('http'):
                    logger.debug(f"  [Thumbnail {idx}/{len(thumbnails)}] No URL extracted after click")
                    continue
                
                if is_excluded_url(url):
                    logger.debug(f"  [Thumbnail {idx}/{len(thumbnails)}] Excluded URL")
                    continue
                
                # Check if it's hero image
                is_hero = False
                if hero_url_normalized:
                    url_normalized = self._normalize_url_for_comparison(url)
                    if hero_url_normalized == url_normalized:
                        is_hero = True
                        logger.info(f"  [Thumbnail {idx}/{len(thumbnails)}] ✗ Skipped hero duplicate")
                
                if not is_hero and url not in all_urls:
                    all_urls.append(url)
                    logger.info(f"  [Thumbnail {idx}/{len(thumbnails)}] ✓ Added gallery URL: {url[:60]}...")
                elif url in all_urls:
                    logger.debug(f"  [Thumbnail {idx}/{len(thumbnails)}] Duplicate URL skipped")
                    
            except Exception as e:
                logger.warning(f"  [Thumbnail {idx}/{len(thumbnails)}] Error: {e}")
                continue
        
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
        # Перевірити на самому елементі
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
        # Перевірити на самому елементі
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
            # Перевірити чи не маленький thumbnail (40x40, 75x75 тощо)
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
    
    def parse_aplus_images(self, output_dir: str, category: str) -> List[str]:
        """
        Parse A+ content images.
        
        Args:
            output_dir: Directory to save images
            category: 'brand' for "From the brand" or 'product' for "Product description"
            
        Returns:
            List of saved image paths
        """
        saved_images = []
        
        if category == 'brand':
            aplus_dir = Path(output_dir) / 'aplus_brand'
            section_markers = ['From the brand', 'From the Brand']
            filename_prefix = 'brand'
        else:
            aplus_dir = Path(output_dir) / 'aplus_product'
            section_markers = ['Product description', 'Product Description']
            filename_prefix = 'A+'
        
        driver = self.browser.get_driver()
        
        # Find A+ content sections - optimized search
        logger.info(f"Searching for A+ {category} sections...")
        import time
        search_start = time.time()
        
        # First, try specific selectors (most likely to match)
        if category == 'brand':
            specific_selectors = [
                '#aplusBrandStory_feature_div',
                '[data-feature-name="aplusBrandStory"]',
            ]
        else:
            specific_selectors = [
                '#productDescription_feature_div',
                '[data-feature-name="productDescription"]',
            ]
        
        # Then try general A+ selectors
        general_selectors = [
            '#aplus_feature_div',
            '#aplus',
            '.aplus-module',
            '[data-feature-name="aplus"]',
        ]
        
        all_selectors = specific_selectors + general_selectors
        logger.info(f"  [A+ {category}] Checking {len(all_selectors)} selectors: {', '.join(all_selectors)}")
        
        # Limit search time - if no sections found in first few selectors, exit early
        max_selector_checks = 3  # Check only first 3 selectors before giving up
        sections_found = False
        
        for idx, selector in enumerate(all_selectors):
            try:
                selector_start = time.time()
                logger.info(f"  [A+ {category}] Checking selector {idx + 1}/{len(all_selectors)}: {selector}")
                sections = driver.find_elements(By.CSS_SELECTOR, selector)
                selector_time = time.time() - selector_start
                
                if not sections:
                    logger.debug(f"  [A+ {category}] Selector '{selector}' found 0 sections ({selector_time:.2f}s)")
                    # If we've checked several selectors and found nothing, exit early
                    if idx >= max_selector_checks and not sections_found:
                        total_time = time.time() - search_start
                        logger.info(f"  [A+ {category}] No sections found after checking {idx + 1} selectors ({total_time:.2f}s), skipping...")
                        return saved_images
                    continue
                
                logger.info(f"  [A+ {category}] Selector '{selector}' found {len(sections)} sections ({selector_time:.2f}s)")
                
                sections_found = True
                logger.debug(f"Found {len(sections)} sections with selector: {selector}")
                
                for section in sections:
                    try:
                        # Quick check: if selector is specific, assume it matches
                        is_target_section = False
                        
                        if selector in specific_selectors:
                            # Specific selector - assume it matches
                            is_target_section = True
                        else:
                            # For general selectors, do quick text check (only first 200 chars)
                            try:
                                section_text = section.text[:200] if section.text else ''
                                section_text = section_text.upper()
                                
                                if category == 'brand':
                                    is_target_section = any(marker.upper() in section_text for marker in section_markers)
                                else:
                                    is_target_section = any(marker.upper() in section_text for marker in section_markers)
                            except:
                                # If can't read text, skip this section
                                continue
                        
                        if not is_target_section:
                            logger.debug(f"Skipping section - doesn't match {category}")
                            continue
                        
                        logger.info(f"Found target section for {category}, extracting images...")
                        
                        # Scroll to section to trigger lazy loading
                        logger.info(f"  [A+ {category}] Scrolling to section...")
                        self.browser.scroll_to_element(section)
                        self.browser._random_sleep(0.1, 0.2)  # Further reduced delay
                        logger.debug(f"  [A+ {category}] Scroll complete")
                        
                        # Find all images in this section
                        logger.info(f"  [A+ {category}] Searching for images in section...")
                        images = section.find_elements(By.TAG_NAME, 'img')
                        logger.info(f"  [A+ {category}] Found {len(images)} img tags in section")
                        
                        # Also check for carousel images
                        carousel_images = []
                        try:
                            logger.info(f"  [A+ {category}] Checking for carousel images...")
                            carousel_images = self._parse_carousel_in_section(section)
                            logger.info(f"  [A+ {category}] Found {len(carousel_images)} carousel images")
                        except Exception as e:
                            logger.debug(f"  [A+ {category}] Carousel parsing skipped: {e}")
                        
                        all_urls = []
                        
                        logger.debug(f"Processing {len(images)} images...")
                        for img in images:
                            url = self._extract_high_res_url_from_element(img)
                            if url and not is_excluded_url(url) and url.startswith('http'):
                                # Avoid duplicates
                                if url not in all_urls:
                                    all_urls.append(url)
                                    logger.debug(f"  [A+ {category}] Added image URL: {url[:60]}...")
                                else:
                                    logger.debug(f"  [A+ {category}] Skipped duplicate URL")
                        
                        # Add carousel images, avoiding duplicates
                        for url in carousel_images:
                            if url and not is_excluded_url(url) and url.startswith('http'):
                                if url not in all_urls:
                                    all_urls.append(url)
                                    logger.debug(f"  [A+ {category}] Added carousel URL: {url[:60]}...")
                        
                        logger.debug(f"Total unique URLs found: {len(all_urls)}")
                        
                        # Create folder and save unique images
                        if all_urls:
                            aplus_dir.mkdir(parents=True, exist_ok=True)
                            logger.info(f"Found {len(all_urls)} images in {category} section, saving...")
                            for idx, url in enumerate(all_urls, 1):
                                output_path = aplus_dir / f'{filename_prefix}{idx}.jpg'
                                logger.debug(f"  [A+ {category}] Saving {filename_prefix}{idx}.jpg from: {url[:60]}...")
                                if save_image_with_dedup(url, str(output_path), self.md5_cache):
                                    saved_images.append(str(output_path))
                                    logger.info(f"  [A+ {category}] ✓ Saved: {filename_prefix}{idx}.jpg")
                                else:
                                    logger.warning(f"  [A+ {category}] ✗ Failed to save: {filename_prefix}{idx}.jpg (check logs for reason)")
                            
                            # After saving, break immediately
                            logger.info(f"Saved {len(saved_images)}/{len(all_urls)} {category} images, moving on...")
                            break
                        else:
                            logger.warning(f"  [A+ {category}] No URLs extracted from {len(images)} img tags and {len(carousel_images)} carousel images")
                    except Exception as e:
                        logger.debug(f"Error processing section: {e}")
                        continue
                    
                # If we found images, stop searching
                if saved_images:
                    break
                    
            except Exception as e:
                logger.debug(f"A+ selector {selector} failed: {e}")
                continue
        
        logger.info(f"A+ {category} images saved: {len(saved_images)}")
        return saved_images
    
    def _parse_carousel_in_section(self, section) -> List[str]:
        """
        Parse carousel images within a section.
        
        Args:
            section: WebElement containing the carousel
            
        Returns:
            List of image URLs
        """
        urls = []
        driver = self.browser.get_driver()
        
        try:
            # Find carousel navigation
            next_buttons = section.find_elements(
                By.CSS_SELECTOR, 
                '.a-carousel-goto-nextpage, [aria-label="Next"], .a-carousel-right'
            )
            
            if not next_buttons:
                return urls
            
            # Get initial images
            visible_images = section.find_elements(By.TAG_NAME, 'img')
            for img in visible_images:
                url = self._extract_high_res_url_from_element(img)
                if url and not is_excluded_url(url) and url.startswith('http'):
                    if url not in urls:
                        urls.append(url)
                        logger.debug(f"Carousel: Added initial image: {url[:60]}...")
            
            # Click through carousel until we see duplicate (by URL or MD5)
            max_clicks = 20  # Increased limit, but will stop on duplicate
            seen_urls = set(urls)  # Track URLs to detect duplicates
            
            for click_num in range(max_clicks):
                try:
                    found_new = False
                    for btn in next_buttons:
                        if btn.is_displayed() and btn.is_enabled():
                            self.browser.click_element(btn)
                            self.browser._random_sleep(0.15, 0.25)  # Small delay for images to load
                            
                            # Get newly visible images
                            new_images = section.find_elements(By.TAG_NAME, 'img')
                            for img in new_images:
                                url = self._extract_high_res_url_from_element(img)
                                if url and not is_excluded_url(url) and url.startswith('http'):
                                    # Check for duplicate by URL
                                    if url in seen_urls:
                                        logger.debug(f"Carousel: duplicate URL found after click {click_num + 1}, stopping")
                                        return urls  # Return immediately on duplicate
                                    
                                    seen_urls.add(url)
                                    urls.append(url)
                                    found_new = True
                                    logger.debug(f"Carousel: Added new image after click {click_num + 1}: {url[:60]}...")
                            
                            # If no new images found, stop clicking
                            if not found_new:
                                logger.debug(f"Carousel: no new images after click {click_num + 1}, stopping")
                                return urls
                            break
                    
                    # If no new images, stop
                    if not found_new:
                        break
                except Exception:
                    break
                    
        except Exception as e:
            logger.debug(f"Carousel parsing failed: {e}")
        
        return urls
    
    def _is_video_thumbnail(self, element) -> bool:
        """Check if thumbnail is a video."""
        try:
            # Check for video indicators in class
            classes = element.get_attribute('class') or ''
            if 'video' in classes.lower():
                return True
            
            # Check text content
            text = element.text.upper()
            if 'VIDEO' in text or 'PLAY' in text:
                return True
            
            # Check aria-label
            aria_label = element.get_attribute('aria-label') or ''
            aria_label = aria_label.upper()
            if 'VIDEO' in aria_label or 'PLAY' in aria_label:
                return True
            
            # Check for play button inside element
            play_buttons = element.find_elements(
                By.CSS_SELECTOR, 
                '.a-icon-play, [data-action="video-player"], .videoThumbnail, .play-button, [aria-label*="video" i]'
            )
            if play_buttons:
                return True
            
            # Check parent for video indicators
            try:
                parent = element.find_element(By.XPATH, './..')
                parent_class = parent.get_attribute('class') or ''
                if 'video' in parent_class.lower():
                    return True
            except:
                pass
            
            # Check for 360 view
            view_360 = element.find_elements(
                By.CSS_SELECTOR,
                '.360-icon, [alt*="360"], [aria-label*="360"]'
            )
            if view_360:
                return True
            
            return False
            
        except Exception:
            return False
    
    def _normalize_url_for_comparison(self, url: str) -> str:
        """
        Normalize URL for comparison by removing query params, fragments, and size indicators.
        Used to detect duplicate images (e.g., hero vs gallery).
        
        Args:
            url: Image URL
            
        Returns:
            Normalized URL for comparison (base URL without size/query params)
        """
        if not url:
            return url
        
        try:
            # Remove query params and fragments
            normalized = url.split('?')[0].split('#')[0]
            
            # Remove ALL size indicators to compare base URLs
            # This ensures hero and gallery versions of same image are detected as duplicates
            normalized = re.sub(r'_AC_S[LXY]\d+_', '_AC_', normalized)
            normalized = re.sub(r'_AC_SX\d+_SY\d+_', '_AC_', normalized)
            normalized = re.sub(r'_S[LXY]\d+_', '_', normalized)
            normalized = re.sub(r'\._[A-Z]{2,}_[A-Z]*\d+_\.', '._AC_.', normalized)
            
            # Remove any remaining size patterns
            normalized = re.sub(r'[SLXY]\d+', '', normalized)
            
            # Clean up double underscores/dots
            normalized = re.sub(r'__+', '_', normalized)
            normalized = re.sub(r'\.\.+', '.', normalized)
            
            return normalized
        except Exception:
            return url.split('?')[0].split('#')[0]
    
    def _get_image_size_from_url(self, url: str) -> int:
        """Extract image size from URL for comparison."""
        match = re.search(r'_SL(\d+)_|_SX(\d+)_|_SY(\d+)_', url)
        if match:
            for group in match.groups():
                if group:
                    return int(group)
        return 0

