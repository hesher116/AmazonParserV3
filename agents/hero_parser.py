"""Hero Image Parser - Parses main product hero image"""
from typing import List, Tuple
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from agents.base_image_parser import BaseImageParser
from utils.file_utils import save_image_with_dedup, is_excluded_url
from utils.logger import get_logger

logger = get_logger(__name__)


class HeroParser(BaseImageParser):
    """Parser for hero (main) product image."""
    
    def parse(self, output_dir: str) -> Tuple[List[str], str]:
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

