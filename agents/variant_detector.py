"""Variant Detector Agent - Detects color/style/size variants"""
import re
from typing import Dict, List, Optional

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException

from core.browser_pool import BrowserPool
from utils.text_utils import clean_html_tags, extract_asin_from_url
from utils.logger import get_logger

logger = get_logger(__name__)


class VariantDetectorAgent:
    """Agent for detecting and handling product variants."""
    
    def __init__(self, browser_pool: BrowserPool):
        self.browser = browser_pool
    
    def parse(self) -> Dict:
        """
        Detect variants on the current page.
        
        Returns:
            Dictionary with variant data
        """
        logger.info("Starting variant detection...")
        
        results = {
            'has_variants': False,
            'variant_types': [],
            'variants': [],
            'errors': []
        }
        
        try:
            variants = self.detect_variants()
            
            if variants:
                results['has_variants'] = True
                results['variants'] = variants
                
                # Extract variant types
                types = set()
                for v in variants:
                    if v.get('type'):
                        types.add(v['type'])
                results['variant_types'] = list(types)
                
                logger.info(f"Found {len(variants)} variants: {results['variant_types']}")
            else:
                logger.info("No variants detected")
                
        except Exception as e:
            logger.error(f"Variant detection error: {e}")
            results['errors'].append(str(e))
        
        return results
    
    def detect_variants(self) -> List[Dict]:
        """
        Detect all variants on the page.
        
        Returns:
            List of variant dictionaries or empty list
        """
        driver = self.browser.get_driver()
        variants = []
        
        # Variant container selectors
        variant_selectors = [
            '#twister',
            '#variation_color_name',
            '#variation_size_name',
            '#variation_style_name',
            '[data-feature-name="twister"]',
            '.a-section.a-spacing-small.a-spacing-top-small',
        ]
        
        for selector in variant_selectors:
            try:
                container = driver.find_element(By.CSS_SELECTOR, selector)
                
                # Determine variant type
                variant_type = self._determine_variant_type(container)
                
                # Find variant options
                option_selectors = [
                    'li[data-defaultasin]',
                    '.swatchAvailable, .swatchSelect',
                    'option[data-a-html-content]',
                    '.a-dropdown-item',
                ]
                
                for opt_selector in option_selectors:
                    options = container.find_elements(By.CSS_SELECTOR, opt_selector)
                    
                    if options:
                        for option in options:
                            variant = self._parse_variant_option(option, variant_type)
                            if variant and variant not in variants:
                                variants.append(variant)
                        break
                
            except NoSuchElementException:
                continue
        
        return variants
    
    def _determine_variant_type(self, container) -> str:
        """Determine the type of variant from container."""
        try:
            # Check container text/label
            text = container.text.lower()
            container_html = container.get_attribute('outerHTML').lower()
            
            if 'color' in text or 'color' in container_html:
                return 'Color'
            elif 'size' in text or 'size' in container_html:
                return 'Size'
            elif 'style' in text or 'style' in container_html:
                return 'Style'
            elif 'pattern' in text or 'pattern' in container_html:
                return 'Pattern'
            elif 'flavor' in text or 'flavor' in container_html:
                return 'Flavor'
            elif 'scent' in text or 'scent' in container_html:
                return 'Scent'
            
            # Try to find label
            try:
                label = container.find_element(By.CSS_SELECTOR, '.a-form-label, label')
                label_text = label.text.lower()
                if 'color' in label_text:
                    return 'Color'
                elif 'size' in label_text:
                    return 'Size'
                elif 'style' in label_text:
                    return 'Style'
            except NoSuchElementException:
                pass
            
            return 'Variant'
            
        except Exception:
            return 'Variant'
    
    def _parse_variant_option(self, element, variant_type: str) -> Optional[Dict]:
        """Parse a single variant option."""
        variant = {
            'type': variant_type,
            'name': None,
            'asin': None,
            'url': None,
            'price': None,
            'available': True,
            'selected': False
        }
        
        try:
            # Get ASIN
            asin = element.get_attribute('data-defaultasin') or element.get_attribute('data-asin')
            if asin:
                variant['asin'] = asin
                variant['url'] = f'https://www.amazon.com/dp/{asin}'
            
            # Get name
            name = (
                element.get_attribute('title') or
                element.get_attribute('data-a-html-content') or
                element.get_attribute('alt') or
                clean_html_tags(element.text)
            )
            if name:
                # Clean up name
                name = re.sub(r'Click to select\s*', '', name, flags=re.IGNORECASE)
                name = name.strip()
                variant['name'] = name
            
            # Check availability
            classes = element.get_attribute('class') or ''
            if 'swatchUnavailable' in classes or 'unavailable' in classes.lower():
                variant['available'] = False
            
            # Check if selected
            if 'swatchSelect' in classes or 'selected' in classes.lower():
                variant['selected'] = True
            
            # Get price if available
            try:
                price_el = element.find_element(
                    By.CSS_SELECTOR, 
                    '.a-price .a-offscreen, .twisterSwatchPrice'
                )
                variant['price'] = clean_html_tags(price_el.text)
            except NoSuchElementException:
                pass
            
            # Only return if we have at least name or ASIN
            if variant['name'] or variant['asin']:
                return variant
                
        except StaleElementReferenceException:
            logger.debug("Stale element in variant parsing")
        except Exception as e:
            logger.debug(f"Variant option parsing error: {e}")
        
        return None
    
    def click_variant(self, variant: Dict) -> bool:
        """
        Click on a variant to load its page.
        
        Args:
            variant: Variant dictionary with ASIN or element info
            
        Returns:
            True if successfully navigated to variant page
        """
        driver = self.browser.get_driver()
        
        # If we have ASIN, navigate directly
        if variant.get('asin'):
            url = f"https://www.amazon.com/dp/{variant['asin']}"
            return self.browser.navigate_to(url)
        
        # Try to find and click the variant element
        try:
            name = variant.get('name', '')
            
            # Find by title or text
            selectors = [
                f'[title*="{name}"]',
                f'[data-a-html-content*="{name}"]',
                f'li[data-defaultasin] img[alt*="{name}"]',
            ]
            
            for selector in selectors:
                try:
                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                    for element in elements:
                        if element.is_displayed():
                            self.browser.click_element(element)
                            self.browser._random_sleep(1.0, 2.0)
                            
                            # Verify page changed
                            new_url = driver.current_url
                            new_asin = extract_asin_from_url(new_url)
                            
                            if new_asin != variant.get('asin'):
                                logger.info(f"Navigated to variant: {name}")
                                return True
                except NoSuchElementException:
                    continue
            
            logger.warning(f"Could not click variant: {name}")
            return False
            
        except Exception as e:
            logger.error(f"Error clicking variant: {e}")
            return False
    
    def get_current_variant_info(self) -> Dict:
        """
        Get information about currently selected variant.
        
        Returns:
            Dictionary with current variant info
        """
        driver = self.browser.get_driver()
        
        info = {
            'asin': extract_asin_from_url(driver.current_url),
            'url': driver.current_url,
            'selected_variants': {}
        }
        
        # Find selected variants
        try:
            selected_elements = driver.find_elements(
                By.CSS_SELECTOR,
                '.swatchSelect, [aria-checked="true"], .a-button-selected'
            )
            
            for el in selected_elements:
                # Get parent label to determine type
                try:
                    parent = el.find_element(By.XPATH, './ancestor::div[contains(@id, "variation")]')
                    parent_id = parent.get_attribute('id') or ''
                    
                    variant_type = 'Unknown'
                    if 'color' in parent_id.lower():
                        variant_type = 'Color'
                    elif 'size' in parent_id.lower():
                        variant_type = 'Size'
                    elif 'style' in parent_id.lower():
                        variant_type = 'Style'
                    
                    name = el.get_attribute('title') or clean_html_tags(el.text)
                    if name:
                        info['selected_variants'][variant_type] = name
                        
                except NoSuchElementException:
                    pass
                    
        except Exception as e:
            logger.debug(f"Error getting current variant info: {e}")
        
        return info

