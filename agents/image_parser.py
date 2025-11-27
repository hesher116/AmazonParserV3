"""Image Parser Agent - Parses hero, gallery, and A+ content images"""
import os
import re
from typing import Dict, List, Set, Optional
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

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
                
                # Try different attributes for image URL
                url = (
                    element.get_attribute('data-old-hires') or
                    element.get_attribute('data-a-dynamic-image') or
                    element.get_attribute('data-src') or
                    element.get_attribute('src')
                )
                
                if url:
                    logger.debug(f"    Found URL: {url[:80]}...")
                    
                    # Handle dynamic image JSON
                    if url.startswith('{'):
                        logger.debug("    Parsing JSON image data...")
                        urls = re.findall(r'"(https://[^"]+)"', url)
                        if urls:
                            logger.debug(f"    Found {len(urls)} URLs in JSON")
                            # Get the highest resolution
                            url = max(urls, key=lambda u: self._get_image_size_from_url(u))
                            logger.debug(f"    Selected highest res: {url[:80]}...")
                    
                    url = get_high_res_url(url)
                    logger.debug(f"    High-res URL: {url[:80]}...")
                    
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
                else:
                    logger.debug("    No URL found in element")
                            
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
        Parse product gallery images using modal popup method.
        Based on proven algorithm: open modal, click through thumbnails, extract high-res images.
        
        Args:
            output_dir: Directory to save images
            hero_url: Hero image URL to exclude from gallery
            
        Returns:
            List of saved image paths
        """
        saved_images = []
        driver = self.browser.get_driver()
        
        logger.info("Scraping Gallery using modal method...")
        
        # Step 1: Find main image to open modal
        main_img = None
        triggers = ['#landingImage', '#imgTagWrapperId', '#main-image-container']
        
        for trigger in triggers:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, trigger)
                for el in elements:
                    if el.is_displayed():
                        main_img = el
                        logger.info(f"✓ Found main image with selector: {trigger}")
                        break
                if main_img:
                    break
            except:
                continue
        
        if not main_img:
            logger.warning("⚠ Could not find main image to open modal, trying fallback...")
            return self._scrape_gallery_fallback(output_dir, hero_url)
        
        # Step 2: Open modal by clicking main image
        try:
            main_img.click()
            logger.info("Clicked main image, waiting for modal...")
            self.browser._random_sleep(1.5, 2.5)  # Wait for modal to appear
        except Exception as e:
            logger.warning(f"⚠ Could not click main image: {e}")
            return self._scrape_gallery_fallback(output_dir, hero_url)
        
        # Step 3: Wait for modal to appear
        try:
            from selenium.webdriver.support import expected_conditions as EC
            wait = WebDriverWait(driver, 5)
            wait.until(EC.visibility_of_any_elements_located((
                By.CSS_SELECTOR, ".a-popover-modal, #ivLargeImage, #imageBlock_feature_div"
            )))
            logger.info("✓ Modal appeared")
        except TimeoutException:
            logger.warning("⚠ Modal did not appear, trying fallback...")
            return self._scrape_gallery_fallback(output_dir, hero_url)
        
        # Step 4: Find thumbnails in modal
        thumb_selectors = [
            "#ivThumbs .ivThumb",
            "#ivImage_0",
            ".a-popover-modal .a-button-thumbnail",
            "#ivRow .ivRowThumb",  # Fallback
        ]
        
        thumbnails = []
        for selector in thumb_selectors:
            try:
                thumbnails = driver.find_elements(By.CSS_SELECTOR, selector)
                if thumbnails:
                    logger.info(f"✓ Found {len(thumbnails)} thumbnails with selector: {selector}")
                    break
            except:
                continue
        
        # If no thumbnails found, try to get current large image
        if not thumbnails:
            logger.warning("⚠ No thumbnails found in modal, trying to get current image...")
            try:
                large_img = driver.find_element(By.CSS_SELECTOR, "#ivLargeImage img")
                src = large_img.get_attribute('src')
                if src:
                    url = get_high_res_url(src)
                    if not is_excluded_url(url) and url.startswith('http'):
                        gallery_dir = Path(output_dir) / 'product'
                        gallery_dir.mkdir(parents=True, exist_ok=True)
                        output_path = gallery_dir / 'product1.jpg'
                        if save_image_with_dedup(url, str(output_path), self.md5_cache):
                            saved_images.append(str(output_path))
                            logger.info(f"  ✓ Saved: product1.jpg")
            except:
                pass
            
            # Close modal and return
            self._close_modal(driver)
            return saved_images
        
        # Step 5: Click through all thumbnails
        logger.info(f"Processing {len(thumbnails)} thumbnails...")
        all_image_urls = []
        hero_md5 = None
        
        # Calculate hero MD5 for exclusion
        if hero_url:
            try:
                hero_data = download_image(hero_url)
                if hero_data:
                    hero_md5 = calculate_md5(hero_data)
            except:
                pass
        
        for i, thumb in enumerate(thumbnails):
            try:
                # Skip video thumbnails
                if self._is_video_thumbnail(thumb):
                    logger.info(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Skipping video thumbnail")
                    continue
                
                # Check for video in class or innerHTML
                try:
                    thumb_class = thumb.get_attribute("class") or ""
                    if "video" in thumb_class.lower():
                        logger.info(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Skipping video (class contains 'video')")
                        continue
                except:
                    pass
                
                # Click thumbnail
                import time
                click_start = time.time()
                logger.info(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Clicking thumbnail...")
                # Use slightly longer delay (0.2-0.4s) to avoid detection - still fast but safer
                self.browser.click_element(thumb, min_delay=0.2, max_delay=0.4)
                click_time = time.time() - click_start
                logger.debug(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Click completed ({click_time:.2f}s)")
                
                # Wait for image to change (more efficient than fixed delay)
                wait_start = time.time()
                logger.debug(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Waiting for image to load...")
                try:
                    wait = WebDriverWait(driver, 3)  # Increased timeout slightly
                    # Get current src before waiting
                    try:
                        current_src = driver.find_element(By.CSS_SELECTOR, "#ivLargeImage img").get_attribute('src')
                        logger.debug(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Current image src: {current_src[:50] if current_src else 'None'}...")
                    except:
                        pass
                    
                    # Wait for image src to change or be loaded
                    wait.until(lambda d: d.find_element(By.CSS_SELECTOR, "#ivLargeImage img").get_attribute('src') and 
                               'loading' not in (d.find_element(By.CSS_SELECTOR, "#ivLargeImage img").get_attribute('src') or '').lower())
                    wait_time = time.time() - wait_start
                    logger.debug(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Image loaded ({wait_time:.2f}s)")
                except Exception as e:
                    # Fallback to small delay if wait fails
                    wait_time = time.time() - wait_start
                    logger.debug(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Wait timeout ({wait_time:.2f}s), using fallback delay: {e}")
                    self.browser._random_sleep(0.2, 0.4)
                
                # Get large image
                try:
                    large_img = driver.find_element(By.CSS_SELECTOR, "#ivLargeImage img")
                    src = large_img.get_attribute('src')
                    
                    if src:
                        # Convert to high resolution
                        url = get_high_res_url(src)
                        logger.debug(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Got image URL: {url[:60]}...")
                        
                        if not is_excluded_url(url) and url.startswith('http'):
                            # Check if it's hero image
                            is_hero = False
                            if i == 0:  # First image is usually hero
                                logger.debug(f"  [Thumbnail {i + 1}/{len(thumbnails)}] First image, marking as hero")
                                is_hero = True
                            elif hero_url and url == hero_url:
                                logger.debug(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Matches hero URL, skipping")
                                is_hero = True
                            elif hero_md5:
                                try:
                                    logger.debug(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Checking MD5 against hero...")
                                    img_data = download_image(url)
                                    if img_data and calculate_md5(img_data) == hero_md5:
                                        logger.debug(f"  [Thumbnail {i + 1}/{len(thumbnails)}] MD5 matches hero, skipping")
                                        is_hero = True
                                except:
                                    pass
                            
                            if not is_hero and url not in all_image_urls:
                                all_image_urls.append(url)
                                logger.info(f"  [Thumbnail {i + 1}/{len(thumbnails)}] ✓ Added to gallery list (total: {len(all_image_urls)})")
                            elif is_hero:
                                logger.debug(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Skipped (hero image)")
                            elif url in all_image_urls:
                                logger.debug(f"  [Thumbnail {i + 1}/{len(thumbnails)}] Skipped (duplicate URL)")
                except NoSuchElementException:
                    logger.warning(f"  [Thumbnail {i + 1}/{len(thumbnails)}] ✗ Could not find large image")
                    continue
                    
            except Exception as e:
                logger.warning(f"  [Thumbnail {i + 1}/{len(thumbnails)}] ✗ Error: {e}")
                continue
        
        # Step 6: Close modal
        self._close_modal(driver)
        
        # Step 7: Save all images
        if not all_image_urls:
            logger.warning("⚠ No gallery images found in modal")
            return saved_images
        
        gallery_dir = Path(output_dir) / 'product'
        gallery_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Downloading {len(all_image_urls)} gallery images...")
        for i, url in enumerate(all_image_urls, 1):
            try:
                output_path = gallery_dir / f'product{i}.jpg'
                logger.info(f"  [Download {i}/{len(all_image_urls)}] Downloading product{i}.jpg...")
                if save_image_with_dedup(url, str(output_path), self.md5_cache):
                    saved_images.append(str(output_path))
                    logger.info(f"  [Download {i}/{len(all_image_urls)}] ✓ Saved: product{i}.jpg")
                else:
                    logger.debug(f"  [Download {i}/{len(all_image_urls)}] ✗ Skipped (duplicate or invalid)")
            except Exception as e:
                logger.warning(f"  [Download {i}/{len(all_image_urls)}] ✗ Failed: {e}")
        
        logger.info(f"✓ Gallery parsing complete: {len(saved_images)} images saved")
        return saved_images
    
    def _scrape_gallery_fallback(self, output_dir: str, hero_url: str = None) -> List[str]:
        """
        Fallback method: scrape gallery directly from page without modal.
        
        Args:
            output_dir: Directory to save images
            hero_url: Hero image URL to exclude
            
        Returns:
            List of saved image paths
        """
        saved_images = []
        driver = self.browser.get_driver()
        
        logger.info("Scraping Gallery (Fallback method)...")
        
        # Find thumbnails on page
        thumb_selectors = [
            "#altImages ul li.item",
            "#av-id-hero-img-wrapper li",
            ".a-button-thumbnail",
        ]
        
        thumbnails = []
        for selector in thumb_selectors:
            try:
                thumbnails = driver.find_elements(By.CSS_SELECTOR, selector)
                if thumbnails:
                    logger.info(f"✓ Found {len(thumbnails)} thumbnails on page: {selector}")
                    break
            except:
                continue
        
        if not thumbnails:
            logger.warning("⚠ No thumbnails found on page")
            return saved_images
        
        all_image_urls = []
        hero_md5 = None
        
        if hero_url:
            try:
                hero_data = download_image(hero_url)
                if hero_data:
                    hero_md5 = calculate_md5(hero_data)
            except:
                pass
        
        # Click through thumbnails on page
        for i, thumb in enumerate(thumbnails):
            try:
                # Skip video
                if self._is_video_thumbnail(thumb):
                    continue
                
                try:
                    thumb_class = thumb.get_attribute("class") or ""
                    if "video" in thumb_class.lower():
                        continue
                    # Check for video icon
                    if thumb.find_elements(By.CSS_SELECTOR, "span.a-icon-video"):
                        continue
                except:
                    pass
                
                # Hover and click
                from selenium.webdriver.common.action_chains import ActionChains
                actions = ActionChains(driver)
                actions.move_to_element(thumb).perform()
                thumb.click()
                self.browser._random_sleep(0.5, 1.0)
                
                # Get main image
                try:
                    main_img = driver.find_element(
                        By.CSS_SELECTOR,
                        "#landingImage, #imgBlkFront, #main-image"
                    )
                    src = main_img.get_attribute('src')
                    
                    if src:
                        url = get_high_res_url(src)
                        
                        if not is_excluded_url(url) and url.startswith('http'):
                            # Check if hero
                            is_hero = False
                            if hero_url and url == hero_url:
                                is_hero = True
                            elif hero_md5:
                                try:
                                    img_data = download_image(url)
                                    if img_data and calculate_md5(img_data) == hero_md5:
                                        is_hero = True
                                except:
                                    pass
                            
                            if not is_hero and url not in all_image_urls:
                                all_image_urls.append(url)
                except NoSuchElementException:
                    continue
                    
            except Exception as e:
                logger.debug(f"Error with thumbnail {i}: {e}")
                continue
        
        # Save images
        if not all_image_urls:
            return saved_images
        
        gallery_dir = Path(output_dir) / 'product'
        gallery_dir.mkdir(parents=True, exist_ok=True)
        
        for i, url in enumerate(all_image_urls, 1):
            try:
                output_path = gallery_dir / f'product{i}.jpg'
                if save_image_with_dedup(url, str(output_path), self.md5_cache):
                    saved_images.append(str(output_path))
                    logger.info(f"  ✓ Saved: product{i}.jpg")
            except Exception as e:
                logger.debug(f"  ✗ Failed: {e}")
        
        return saved_images
    
    def _close_modal(self, driver):
        """Close modal popup."""
        try:
            close_selectors = [
                ".a-popover-header .a-button-close",
                "#ivCloseButton",
                "button[data-action='a-popover-close']",
                '.a-button-close',
                '[aria-label*="Close" i]',
            ]
            
            for selector in close_selectors:
                try:
                    close_btn = driver.find_element(By.CSS_SELECTOR, selector)
                    if close_btn.is_displayed():
                        close_btn.click()
                        logger.info("Modal closed")
                        self.browser._random_sleep(1, 1.5)
                        return
                except:
                    continue
            
            # Try ESC key
            from selenium.webdriver.common.keys import Keys
            driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.ESCAPE)
            self.browser._random_sleep(0.5, 1.0)
        except Exception as e:
            logger.debug(f"Could not close modal: {e}")
            # Try clicking outside
            try:
                from selenium.webdriver.common.action_chains import ActionChains
                ActionChains(driver).move_by_offset(10, 10).click().perform()
            except:
                pass
    
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
                            url = img.get_attribute('data-src') or img.get_attribute('src')
                            if url and not is_excluded_url(url):
                                all_urls.append(get_high_res_url(url))
                        
                        # Add carousel images, avoiding duplicates
                        for url in carousel_images:
                            if url not in all_urls:
                                all_urls.append(url)
                        
                        logger.debug(f"Total unique URLs found: {len(all_urls)}")
                        
                        # Create folder and save unique images
                        if all_urls:
                            aplus_dir.mkdir(parents=True, exist_ok=True)
                            logger.info(f"Found {len(all_urls)} images in {category} section, saving...")
                            for idx, url in enumerate(all_urls):
                                output_path = aplus_dir / f'{filename_prefix}{idx + 1}.jpg'
                                if save_image_with_dedup(url, str(output_path), self.md5_cache):
                                    saved_images.append(str(output_path))
                                    logger.debug(f"  Saved: {filename_prefix}{idx + 1}.jpg")
                            
                            # After saving, break immediately
                            logger.info(f"Saved {len(saved_images)} {category} images, moving on...")
                            break
                        else:
                            logger.debug(f"No images found in {category} section")
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
                url = img.get_attribute('data-src') or img.get_attribute('src')
                if url and not is_excluded_url(url):
                    urls.append(get_high_res_url(url))
            
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
                                url = img.get_attribute('data-src') or img.get_attribute('src')
                                if url and not is_excluded_url(url):
                                    high_res_url = get_high_res_url(url)
                                    
                                    # Check for duplicate by URL
                                    if high_res_url in seen_urls:
                                        logger.debug(f"Carousel: duplicate URL found after click {click_num + 1}, stopping")
                                        return urls  # Return immediately on duplicate
                                    
                                    seen_urls.add(high_res_url)
                                    urls.append(high_res_url)
                                    found_new = True
                            
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
    
    def _get_image_size_from_url(self, url: str) -> int:
        """Extract image size from URL for comparison."""
        match = re.search(r'_SL(\d+)_|_SX(\d+)_|_SY(\d+)_', url)
        if match:
            for group in match.groups():
                if group:
                    return int(group)
        return 0

