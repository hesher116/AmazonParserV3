"""Text Parser Agent - Parses all text information from product page"""
import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from agents.base_parser import BaseParser
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


class TextParserAgent(BaseParser):
    """Agent for parsing text information from Amazon product page."""
    
    def __init__(self, browser_pool: BrowserPool, dom_soup: Optional[BeautifulSoup] = None):
        super().__init__(browser_pool, dom_soup)
    
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
            'price': None,
            'asin': None,
            'product_description': None,
            'product_overview': {},
            'about_this_item': [],
            'ingredients': None,
            'important_information': {},
            'sustainability_features': None,
            'technical_details': {},
            'product_details': {},
            'errors': []
        }
        
        try:
            results['title'] = self._parse_title()
            results['brand'] = self._parse_brand()
            results['price'] = self._parse_price()
            results['asin'] = self._parse_asin()
            results['product_description'] = self._parse_product_description()
            results['product_overview'] = self._parse_product_overview()
            results['about_this_item'] = self._parse_about_this_item()
            results['ingredients'] = self._parse_ingredients()
            results['important_information'] = self._parse_important_information()
            results['sustainability_features'] = self._parse_sustainability_features()
            results['technical_details'] = self._parse_technical_details()
            results['product_details'] = self._parse_product_details()
            
            logger.info("Text parsing complete")
            
        except Exception as e:
            logger.error(f"Text parsing error: {e}")
            results['errors'].append(str(e))
        
        return results
    
    def _parse_title(self) -> Optional[str]:
        """Parse product title."""
        # Try popular selectors first (from metrics if available)
        selectors = [
            '#productTitle',
            '#title',
            'h1.a-size-large',
            '[data-feature-name="title"]',
            '[data-automation-id="title"]',  # Additional fallback
            'h1',  # Generic fallback
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                title = self.get_text_from_element(element)
                title = clean_html_tags(title)
                if title:
                    logger.debug(f"Title found: {title[:50]}...")
                    # Record selector success if metrics available
                    if hasattr(self, 'metrics'):
                        self.metrics.record_selector_success(selector, True)
                    return title
            # Record selector failure if metrics available
            if hasattr(self, 'metrics'):
                self.metrics.record_selector_success(selector, False)
        
        logger.warning("Title not found")
        return None
    
    def _parse_brand(self) -> Optional[str]:
        """Parse brand name."""
        selectors = [
            '#bylineInfo',
            '.a-link-normal[href*="/stores/"]',
            '#brand',
            '[data-feature-name="bylineInfo"]',
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                brand = self.get_text_from_element(element)
                brand = clean_html_tags(brand)
                # Clean up "Visit the X Store" or "Brand: X"
                brand = brand.replace('Visit the', '').replace('Store', '')
                brand = brand.replace('Brand:', '').strip()
                if brand:
                    logger.debug(f"Brand found: {brand}")
                    return brand
        
        return None
    
    def _parse_price(self) -> Optional[str]:
        """Parse price information and return in format 'Price($): 6.99'."""
        # Try to find main price block first (more specific - Amazon structure)
        main_price_blocks = [
            '#corePriceDisplay_desktop_feature_div',
            '#corePrice_feature_div',
            '#priceblock_ourprice',
            '#priceblock_dealprice',
            '#priceblock_saleprice',
            '#apexPriceToPay',
        ]
        
        for block_selector in main_price_blocks:
            block = self.find_element_by_selector(block_selector, use_dom=True)
            if block:
                # Find price within this block - prioritize .a-offscreen
                if hasattr(block, 'select_one'):  # BeautifulSoup
                    price_el = block.select_one('.a-price .a-offscreen, .a-offscreen, .a-price-whole')
                else:  # Selenium
                    try:
                        price_el = block.find_element(By.CSS_SELECTOR, '.a-price .a-offscreen, .a-offscreen, .a-price-whole')
                    except:
                        price_el = block
                
                if price_el:
                    price_text = self.get_text_from_element(price_el)
                    parsed = parse_price(price_text)
                    if parsed['current_price']:
                        price_value = parsed['current_price'].replace('$', '').replace(',', '')
                        if price_value:
                            result = f"Price($): {price_value}"
                            logger.debug(f"Price found: {result}")
                            return result
        
        # Fallback: try direct price selectors in main price area only
        price_selectors = [
            '#apexPriceToPay .a-offscreen',
            '.a-price.a-text-price.a-size-medium.apexPriceToPay .a-offscreen',
            '#corePriceDisplay_desktop_feature_div .a-price .a-offscreen',
            '#corePrice_feature_div .a-price .a-offscreen',
            '#priceBlock_feature_div .a-price .a-offscreen',
            '#price .a-price .a-offscreen',
            '.a-price.a-text-price .a-offscreen',  # More generic but still in price block
        ]
        
        for selector in price_selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                price_text = self.get_text_from_element(element)
                parsed = parse_price(price_text)
                if parsed['current_price']:
                    price_value = parsed['current_price'].replace('$', '').replace(',', '')
                    if price_value:
                        result = f"Price($): {price_value}"
                        logger.debug(f"Price found: {result}")
                        return result
        
        logger.debug("Price not found")
        return None
    
    def _parse_product_description(self) -> Optional[str]:
        """Parse product description text."""
        selectors = [
            '#productDescription_feature_div',
            '#aplus_feature_div',
            '[data-feature-name="productDescription"]',
            '[data-feature-name="aplus"]',
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                # Extract text content, excluding navigation elements
                if hasattr(element, 'select'):  # BeautifulSoup
                    # Remove navigation buttons and headings
                    for nav in element.select('.a-carousel-control, .a-button, h2'):
                        nav.decompose()
                    text = element.get_text(separator=' ', strip=True)
                else:  # Selenium
                    # Try to get text excluding navigation
                    try:
                        nav_elements = element.find_elements(By.CSS_SELECTOR, '.a-carousel-control, .a-button, h2')
                        for nav in nav_elements:
                            element.execute_script("arguments[0].remove();", nav)
                    except:
                        pass
                    text = element.text.strip()
                
                text = clean_html_tags(text)
                text = filter_ad_phrases(text)
                
                # Remove common navigation text
                text = re.sub(r'(Previous page|Next page|Product description|Product Description)', '', text, flags=re.IGNORECASE)
                text = re.sub(r'\s+', ' ', text).strip()
                
                if text and len(text) > 20:  # Minimum meaningful length
                    logger.debug(f"Product description found: {len(text)} chars")
                    return text
        
        logger.debug("Product description not found")
        return None
    
    def _parse_asin(self) -> Optional[str]:
        """Parse ASIN from URL or page."""
        # Try URL first
        url = self.browser.get_current_url()
        asin = extract_asin_from_url(url)
        if asin:
            return asin
        
        # Try page elements
        selectors = [
            '[data-asin]',
            '#ASIN',
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                asin = self.get_attribute_from_element(element, 'data-asin') or \
                       self.get_attribute_from_element(element, 'value')
                if asin and len(asin) == 10:
                    return asin
        
        return None
    
    def _parse_product_overview(self) -> Dict:
        """Parse product overview table."""
        result = {}
        
        selectors = [
            '#productOverview_feature_div table',
            '#prodDetails table',
            '.a-normal.a-spacing-micro',
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                result = extract_table_data(element)
                if result:
                    logger.debug(f"Product overview found: {len(result)} items")
                    break
        
        return result
    
    def _parse_about_this_item(self) -> List[str]:
        """Parse 'About this item' bullet points."""
        items = []
        
        selectors = [
            '#feature-bullets ul',
            '#productFactsDesktopExpander ul',
            '[data-feature-name="featurebullets"] ul',
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                items = extract_list_items(element)
                # Filter out ad phrases
                items = [filter_ad_phrases(item) for item in items if item]
                items = [item for item in items if item]  # Remove empty after filtering
                if items:
                    logger.debug(f"About this item: {len(items)} bullets")
                    break
        
        return items
    
    def _parse_ingredients(self) -> Optional[str]:
        """Parse ingredients section."""
        selectors = [
            '#important-information .content',
            '#ingredients_feature_div',
            '[data-feature-name="ingredients"]',
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                text = self.get_text_from_element(element)
                text = clean_html_tags(text)
                if text and 'ingredient' in text.lower():
                    return filter_ad_phrases(text)
        
        return None
    
    def _parse_important_information(self) -> Dict:
        """Parse 'Important Information' section (excluding sustainability features)."""
        result = {}
        
        section = self.find_element_by_selector('#important-information', use_dom=True)
        if section:
            # Parse subsections within #important-information only
            if hasattr(section, 'select'):  # BeautifulSoup
                subsections = section.select('.a-section.content, .content')
            else:  # Selenium
                try:
                    subsections = section.find_elements(By.CSS_SELECTOR, '.a-section.content, .content')
                except:
                    subsections = []
            
            for sub in subsections:
                heading = None
                
                # Find heading first
                if hasattr(sub, 'select_one'):  # BeautifulSoup
                    heading = sub.select_one('h4, h5, .a-text-bold')
                elif hasattr(sub, 'find_element'):  # Selenium
                    try:
                        heading = sub.find_element(By.CSS_SELECTOR, 'h4, h5, .a-text-bold')
                    except:
                        continue
                
                if heading:
                    key = clean_html_tags(self.get_text_from_element(heading))
                    
                    # Skip sustainability-related sections
                    if key and ('sustainability' in key.lower() or 'environment' in key.lower()):
                        continue
                    
                    # Collect all paragraphs after heading (skip empty ones)
                    if hasattr(sub, 'select'):  # BeautifulSoup
                        paragraphs = sub.select('p')
                        # Filter out empty paragraphs and get text
                        text_parts = []
                        for p in paragraphs:
                            text = p.get_text(strip=True)
                            if text:  # Skip empty paragraphs
                                text_parts.append(text)
                        value = ' '.join(text_parts)
                    else:  # Selenium
                        try:
                            paragraphs = sub.find_elements(By.CSS_SELECTOR, 'p')
                            text_parts = []
                            for p in paragraphs:
                                text = p.text.strip()
                                if text:  # Skip empty paragraphs
                                    text_parts.append(text)
                            value = ' '.join(text_parts)
                        except:
                            # Fallback: get all text from subsection
                            value = sub.text.strip()
                    
                    value = clean_html_tags(value)
                    value = filter_ad_phrases(value)
                    
                    if key and value:
                        result[key] = value
        
        return result
    
    def _parse_sustainability_features(self) -> Optional[str]:
        """Parse 'Sustainability Features' section separately."""
        selectors = [
            '#aplusSustainabilityStory_feature_div',
            '[data-feature-name="aplusSustainabilityStory"]',
            '#sustainability_feature_div',
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                # Extract text content
                if hasattr(element, 'get_text'):  # BeautifulSoup
                    # Remove navigation elements
                    for nav in element.select('.a-carousel-control, .a-button, h2'):
                        nav.decompose()
                    text = element.get_text(separator=' ', strip=True)
                else:  # Selenium
                    text = element.text.strip()
                
                text = clean_html_tags(text)
                text = filter_ad_phrases(text)
                
                # Remove common navigation text
                text = re.sub(r'(Previous page|Next page|Sustainability|Sustainability Features)', '', text, flags=re.IGNORECASE)
                text = re.sub(r'\s+', ' ', text).strip()
                
                if text and len(text) > 20:  # Minimum meaningful length
                    logger.debug(f"Sustainability features found: {len(text)} chars")
                    return text
        
        logger.debug("Sustainability features not found")
        return None
    
    def _parse_technical_details(self) -> Dict:
        """Parse technical details table."""
        result = {}
        
        selectors = [
            '#productDetails_techSpec_section_1',
            '#techSpecifications',
            '[data-feature-name="technicalSpecifications"]',
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                result = extract_table_data(element)
                if result:
                    logger.debug(f"Technical details found: {len(result)} items")
                    break
        
        return result
    
    def _parse_product_details(self) -> Dict:
        """Parse product details section."""
        result = {}
        
        # Try table format first
        selectors = [
            '#productDetails_detailBullets_sections1',
            '#prodDetails',
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                result = extract_table_data(element)
                if result:
                    logger.debug(f"Product details found: {len(result)} items")
                    break
        
        # Try bullet format (Amazon structure: li > span.a-list-item > span.a-text-bold + text)
        if not result:
            bullets = self.find_elements_by_selector('#detailBullets_feature_div li', use_dom=True)
            for bullet in bullets:
                if hasattr(bullet, 'select_one'):  # BeautifulSoup
                    # Look for structure: span.a-list-item > span.a-text-bold (key) + rest (value)
                    list_item = bullet.select_one('span.a-list-item')
                    if list_item:
                        bold_span = list_item.select_one('span.a-text-bold')
                        if bold_span:
                            key = clean_html_tags(bold_span.get_text(strip=True))
                            # Get all text after bold span
                            bold_span.extract()  # Remove bold span to get remaining text
                            value = clean_html_tags(list_item.get_text(separator=' ', strip=True))
                        else:
                            # Fallback: try to split by colon
                            text = clean_html_tags(list_item.get_text(strip=True))
                            if ':' in text:
                                parts = text.split(':', 1)
                                if len(parts) == 2:
                                    key = parts[0].strip()
                                    value = parts[1].strip()
                                else:
                                    continue
                            else:
                                continue
                    else:
                        # Fallback: get all text and split by colon
                        text = clean_html_tags(bullet.get_text(strip=True))
                        if ':' in text:
                            parts = text.split(':', 1)
                            if len(parts) == 2:
                                key = parts[0].strip()
                                value = parts[1].strip()
                            else:
                                continue
                        else:
                            continue
                else:  # Selenium
                    try:
                        list_item = bullet.find_element(By.CSS_SELECTOR, 'span.a-list-item')
                        try:
                            bold_span = list_item.find_element(By.CSS_SELECTOR, 'span.a-text-bold')
                            key = clean_html_tags(bold_span.text.strip())
                            # Get all text from list_item, then remove bold text
                            full_text = list_item.text.strip()
                            bold_text = bold_span.text.strip()
                            value = full_text.replace(bold_text, '', 1).strip()
                        except:
                            # Fallback: split by colon
                            text = clean_html_tags(list_item.text.strip())
                            if ':' in text:
                                parts = text.split(':', 1)
                                if len(parts) == 2:
                                    key = parts[0].strip()
                                    value = parts[1].strip()
                                else:
                                    continue
                            else:
                                continue
                    except:
                        # Fallback: get all text and split by colon
                        text = clean_html_tags(bullet.text.strip())
                        if ':' in text:
                            parts = text.split(':', 1)
                            if len(parts) == 2:
                                key = parts[0].strip()
                                value = parts[1].strip()
                            else:
                                continue
                        else:
                            continue
                
                if key and value:
                    value = filter_ad_phrases(value)
                    if value:  # Only add if value is not empty after filtering
                        result[key] = value
        
        return result

