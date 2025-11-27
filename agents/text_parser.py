"""Text Parser Agent - Parses all text information from product page"""
from typing import Dict, List, Optional

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from core.browser_pool import BrowserPool
from utils.text_utils import (
    clean_html_tags, 
    filter_ad_phrases, 
    extract_table_data,
    extract_list_items,
    parse_price,
    parse_rating,
    extract_asin_from_url
)
from utils.logger import get_logger

logger = get_logger(__name__)


class TextParserAgent:
    """Agent for parsing text information from Amazon product page."""
    
    def __init__(self, browser_pool: BrowserPool):
        self.browser = browser_pool
    
    def parse(self) -> Dict:
        """
        Parse all text information from the current page.
        
        Returns:
            Dictionary with all parsed text data
        """
        logger.info("Starting text parsing...")
        
        results = {
            'title': None,
            'brand': None,
            'price': {},
            'asin': None,
            'product_overview': {},
            'about_this_item': [],
            'ingredients': None,
            'important_information': {},
            'technical_details': {},
            'product_details': {},
            'errors': []
        }
        
        try:
            results['title'] = self._parse_title()
            results['brand'] = self._parse_brand()
            results['price'] = self._parse_price()
            results['asin'] = self._parse_asin()
            results['product_overview'] = self._parse_product_overview()
            results['about_this_item'] = self._parse_about_this_item()
            results['ingredients'] = self._parse_ingredients()
            results['important_information'] = self._parse_important_information()
            results['technical_details'] = self._parse_technical_details()
            results['product_details'] = self._parse_product_details()
            
            logger.info("Text parsing complete")
            
        except Exception as e:
            logger.error(f"Text parsing error: {e}")
            results['errors'].append(str(e))
        
        return results
    
    def _parse_title(self) -> Optional[str]:
        """Parse product title."""
        driver = self.browser.get_driver()
        
        selectors = [
            '#productTitle',
            '#title',
            'h1.a-size-large',
            '[data-feature-name="title"]',
        ]
        
        for selector in selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                title = clean_html_tags(element.text)
                if title:
                    logger.debug(f"Title found: {title[:50]}...")
                    return title
            except NoSuchElementException:
                continue
        
        logger.warning("Title not found")
        return None
    
    def _parse_brand(self) -> Optional[str]:
        """Parse brand name."""
        driver = self.browser.get_driver()
        
        selectors = [
            '#bylineInfo',
            '.a-link-normal[href*="/stores/"]',
            '#brand',
            '[data-feature-name="bylineInfo"]',
        ]
        
        for selector in selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                brand = clean_html_tags(element.text)
                # Clean up "Visit the X Store" or "Brand: X"
                brand = brand.replace('Visit the', '').replace('Store', '')
                brand = brand.replace('Brand:', '').strip()
                if brand:
                    logger.debug(f"Brand found: {brand}")
                    return brand
            except NoSuchElementException:
                continue
        
        return None
    
    def _parse_price(self) -> Dict:
        """Parse price information."""
        driver = self.browser.get_driver()
        
        result = {
            'current_price': None,
            'original_price': None,
            'currency': 'USD',
            'savings': None
        }
        
        # Current price selectors
        price_selectors = [
            '.a-price .a-offscreen',
            '#priceblock_ourprice',
            '#priceblock_dealprice',
            '#priceblock_saleprice',
            '.a-price-whole',
            '[data-a-color="price"] .a-offscreen',
        ]
        
        for selector in price_selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                price_text = element.get_attribute('textContent') or element.text
                parsed = parse_price(price_text)
                if parsed['current_price']:
                    result['current_price'] = parsed['current_price']
                    break
            except NoSuchElementException:
                continue
        
        # Original price (if discounted)
        original_selectors = [
            '.a-text-price .a-offscreen',
            '#listPrice',
            '.a-price[data-a-strike="true"] .a-offscreen',
        ]
        
        for selector in original_selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                price_text = element.get_attribute('textContent') or element.text
                parsed = parse_price(price_text)
                if parsed['current_price']:
                    result['original_price'] = parsed['current_price']
                    break
            except NoSuchElementException:
                continue
        
        # Savings
        try:
            savings_element = driver.find_element(
                By.CSS_SELECTOR, 
                '.savingsPercentage, .a-color-price.a-size-small'
            )
            result['savings'] = clean_html_tags(savings_element.text)
        except NoSuchElementException:
            pass
        
        logger.debug(f"Price found: {result}")
        return result
    
    def _parse_asin(self) -> Optional[str]:
        """Parse ASIN from URL or page."""
        driver = self.browser.get_driver()
        
        # Try URL first
        url = driver.current_url
        asin = extract_asin_from_url(url)
        if asin:
            return asin
        
        # Try page elements
        selectors = [
            '[data-asin]',
            '#ASIN',
        ]
        
        for selector in selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                asin = element.get_attribute('data-asin') or element.get_attribute('value')
                if asin and len(asin) == 10:
                    return asin
            except NoSuchElementException:
                continue
        
        return None
    
    def _parse_product_overview(self) -> Dict:
        """Parse product overview table."""
        driver = self.browser.get_driver()
        
        result = {}
        
        selectors = [
            '#productOverview_feature_div table',
            '#prodDetails table',
            '.a-normal.a-spacing-micro',
        ]
        
        for selector in selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                result = extract_table_data(element)
                if result:
                    logger.debug(f"Product overview found: {len(result)} items")
                    break
            except NoSuchElementException:
                continue
        
        return result
    
    def _parse_about_this_item(self) -> List[str]:
        """Parse 'About this item' bullet points."""
        driver = self.browser.get_driver()
        
        items = []
        
        selectors = [
            '#feature-bullets ul',
            '#productFactsDesktopExpander ul',
            '[data-feature-name="featurebullets"] ul',
        ]
        
        for selector in selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                items = extract_list_items(element)
                # Filter out ad phrases
                items = [filter_ad_phrases(item) for item in items if item]
                items = [item for item in items if item]  # Remove empty after filtering
                if items:
                    logger.debug(f"About this item: {len(items)} bullets")
                    break
            except NoSuchElementException:
                continue
        
        return items
    
    def _parse_ingredients(self) -> Optional[str]:
        """Parse ingredients section."""
        driver = self.browser.get_driver()
        
        selectors = [
            '#important-information .content',
            '#ingredients_feature_div',
            '[data-feature-name="ingredients"]',
        ]
        
        for selector in selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                text = clean_html_tags(element.text)
                if text and 'ingredient' in text.lower():
                    return filter_ad_phrases(text)
            except NoSuchElementException:
                continue
        
        return None
    
    def _parse_important_information(self) -> Dict:
        """Parse 'Important Information' section."""
        driver = self.browser.get_driver()
        
        result = {}
        
        try:
            section = driver.find_element(By.CSS_SELECTOR, '#important-information')
            
            # Parse subsections
            subsections = section.find_elements(By.CSS_SELECTOR, '.a-section')
            for sub in subsections:
                try:
                    heading = sub.find_element(By.CSS_SELECTOR, 'h4, h5, .a-text-bold')
                    content = sub.find_element(By.CSS_SELECTOR, '.content, p')
                    
                    key = clean_html_tags(heading.text)
                    value = clean_html_tags(content.text)
                    
                    if key and value:
                        result[key] = filter_ad_phrases(value)
                except NoSuchElementException:
                    continue
                    
        except NoSuchElementException:
            pass
        
        return result
    
    def _parse_technical_details(self) -> Dict:
        """Parse technical details table."""
        driver = self.browser.get_driver()
        
        result = {}
        
        selectors = [
            '#productDetails_techSpec_section_1',
            '#techSpecifications',
            '[data-feature-name="technicalSpecifications"]',
        ]
        
        for selector in selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                result = extract_table_data(element)
                if result:
                    logger.debug(f"Technical details found: {len(result)} items")
                    break
            except NoSuchElementException:
                continue
        
        return result
    
    def _parse_product_details(self) -> Dict:
        """Parse product details section."""
        driver = self.browser.get_driver()
        
        result = {}
        
        selectors = [
            '#productDetails_detailBullets_sections1',
            '#detailBullets_feature_div',
            '#prodDetails',
        ]
        
        for selector in selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                result = extract_table_data(element)
                if result:
                    logger.debug(f"Product details found: {len(result)} items")
                    break
            except NoSuchElementException:
                continue
        
        # Also try bullet format
        if not result:
            try:
                bullets = driver.find_elements(
                    By.CSS_SELECTOR, 
                    '#detailBullets_feature_div li'
                )
                for bullet in bullets:
                    text = clean_html_tags(bullet.text)
                    if ':' in text:
                        parts = text.split(':', 1)
                        if len(parts) == 2:
                            key = parts[0].strip()
                            value = parts[1].strip()
                            if key and value:
                                result[key] = filter_ad_phrases(value)
            except NoSuchElementException:
                pass
        
        return result

