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
            'product_overview': {},
            'about_this_item': [],
            'from_the_brand': None,
            'sustainability_features': None,
            'product_description': None,
            'product_details': {},
            'important_information': {},
            'technical_details': {},
            'ingredients': None,
            'errors': []
        }
        
        try:
            results['title'] = self._parse_title()
            results['brand'] = self._parse_brand()
            results['price'] = self._parse_price()
            results['asin'] = self._parse_asin()
            results['product_overview'] = self._parse_product_overview()
            results['about_this_item'] = self._parse_about_this_item()
            results['from_the_brand'] = self._parse_from_the_brand()
            results['sustainability_features'] = self._parse_sustainability_features()
            results['product_description'] = self._parse_product_description()
            results['product_details'] = self._parse_product_details()
            results['important_information'] = self._parse_important_information()
            results['technical_details'] = self._parse_technical_details()
            results['ingredients'] = self._parse_ingredients()
            
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
        """Parse product description text, including structured content (tables, columns, Q&A)."""
        selectors = [
            '#productDescription_feature_div',
            '#aplus_feature_div',
            '[data-feature-name="productDescription"]',
            '[data-feature-name="aplus"]',
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                # Check if there's structured content (table, columns, comparison)
                if hasattr(element, 'select'):  # BeautifulSoup
                    # Remove navigation buttons and headings
                    for nav in element.select('.a-carousel-control, .a-button, h2'):
                        nav.decompose()
                    
                    # Check for Q&A content first (aplus-question/aplus-answer)
                    qa_pairs = element.select('.faq-block, li[id*="faq-qa-pair"]')
                    if qa_pairs:
                        qa_texts = []
                        for qa_pair in qa_pairs:
                            question = qa_pair.select_one('.aplus-question, .aplus-p1')
                            answer = qa_pair.select_one('.aplus-answer, .aplus-p2')
                            
                            if question and answer:
                                q_text = question.get_text(strip=True)
                                a_text = answer.get_text(strip=True)
                                if q_text and a_text:
                                    # Format: Question|||Answer (using ||| as separator between pairs)
                                    qa_texts.append(f"{q_text}|||{a_text}")
                        
                        if qa_texts:
                            # Mark as Q&A content with special prefix, use ||| as separator between pairs
                            text = "Q&A_CONTENT:" + "|||PAIR_SEP|||".join(qa_texts)
                            text = clean_html_tags(text)
                            text = filter_ad_phrases(text)
                            if text and len(text) > 20:
                                logger.debug(f"Product description (Q&A) found: {len(qa_texts)} pairs")
                                return text
                    
                    # Try to extract structured content (tables, columns)
                    tables = element.select('table')
                    columns = element.select('.a-column, .a-row, [class*="column"], [class*="comparison"]')
                    
                    if tables:
                        # Extract table data
                        table_texts = []
                        for table in tables:
                            rows = table.select('tr')
                            for row in rows:
                                cells = row.select('td, th')
                                if cells:
                                    row_text = ' | '.join([cell.get_text(strip=True) for cell in cells if cell.get_text(strip=True)])
                                    if row_text:
                                        table_texts.append(row_text)
                        if table_texts:
                            text = '\n'.join(table_texts)
                            text = clean_html_tags(text)
                            text = filter_ad_phrases(text)
                            if text and len(text) > 20:
                                logger.debug(f"Product description (table) found: {len(text)} chars")
                                return text
                    
                    if columns:
                        # Extract column-based content (like product comparison)
                        # Group columns by rows for better structure
                        rows = element.select('.a-row, [class*="row"]')
                        if rows:
                            row_texts = []
                            for row in rows:
                                cols = row.select('.a-column, [class*="column"], [class*="col"]')
                                if cols:
                                    col_texts = []
                                    for col in cols:
                                        col_text = col.get_text(separator=' ', strip=True)
                                        if col_text and len(col_text) > 5:
                                            col_texts.append(col_text)
                                    if col_texts:
                                        row_texts.append(' | '.join(col_texts))
                            if row_texts:
                                text = '\n'.join(row_texts)
                                text = clean_html_tags(text)
                                text = filter_ad_phrases(text)
                                # Remove common navigation text
                                text = re.sub(r'(Previous page|Next page|Product description|Product Description)', '', text, flags=re.IGNORECASE)
                                text = re.sub(r'\s+', ' ', text).strip()
                                if text and len(text) > 20:
                                    logger.debug(f"Product description (columns) found: {len(text)} chars")
                                    return text
                        
                        # Fallback: extract individual columns
                        column_texts = []
                        for col in columns:
                            col_text = col.get_text(separator=' | ', strip=True)
                            if col_text and len(col_text) > 10:
                                column_texts.append(col_text)
                        if column_texts:
                            text = '\n'.join(column_texts)
                            text = clean_html_tags(text)
                            text = filter_ad_phrases(text)
                            # Remove common navigation text
                            text = re.sub(r'(Previous page|Next page|Product description|Product Description)', '', text, flags=re.IGNORECASE)
                            text = re.sub(r'\s+', ' ', text).strip()
                            if text and len(text) > 20:
                                logger.debug(f"Product description (columns) found: {len(text)} chars")
                                return text
                    
                    # Fallback: regular text extraction
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
    
    def _parse_from_the_brand(self) -> Optional[str]:
        """Parse 'From the Brand' section."""
        selectors = [
            '#aplusBrandStory_feature_div',
            '[data-feature-name="aplusBrandStory"]',
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
                text = re.sub(r'(Previous page|Next page|From the brand|From the Brand)', '', text, flags=re.IGNORECASE)
                text = re.sub(r'\s+', ' ', text).strip()
                
                if text and len(text) > 20:  # Minimum meaningful length
                    logger.debug(f"From the brand found: {len(text)} chars")
                    return text
        
        logger.debug("From the brand not found")
        return None
    
    def _parse_sustainability_features(self) -> Optional[str]:
        """Parse 'Sustainability Features' section - extract all information including certifications."""
        selectors = [
            '#climatePledgeFriendly',  # Main sustainability section
            '#aplusSustainabilityStory_feature_div',
            '[data-feature-name="aplusSustainabilityStory"]',
            '#sustainability_feature_div',
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                # Extract all text content including certifications
                if hasattr(element, 'select'):  # BeautifulSoup
                    # Remove main heading "Sustainability features" (it's already in DOCX section title)
                    for h2 in element.select('h2'):
                        h2_text = h2.get_text(strip=True).lower()
                        if 'sustainability features' in h2_text:
                            h2.decompose()
                    
                    # Remove footers with "Discover more" and "Learn more" links
                    for footer in element.select('footer, .cpf-dpx-footer, .cpf-dpx-sticky-footer'):
                        footer_text = footer.get_text(strip=True).lower()
                        if 'discover more' in footer_text or 'learn more' in footer_text or 'climate pledge friendly' in footer_text:
                            footer.decompose()
                    
                    # Collect all sustainability information in order
                    feature_parts = []
                    seen_texts = set()  # Track seen texts to avoid duplicates
                    
                    # Main description paragraph ("This product has sustainability features recognized...")
                    main_desc = element.select_one('p.a-size-base.a-color-base')
                    if main_desc:
                        desc_text = main_desc.get_text(strip=True)
                        if desc_text and len(desc_text) > 20:
                            # Normalize for duplicate check
                            desc_normalized = desc_text.lower().strip()
                            if desc_normalized not in seen_texts:
                                seen_texts.add(desc_normalized)
                                feature_parts.append(desc_text)
                    
                    # Look for sections with sustainability content (like "Organic content")
                    sections = element.select('.a-section')
                    for section in sections:
                        # Skip footers and already processed certifications
                        if section.select_one('footer, .cpf-dpx-footer'):
                            continue
                        
                        # Look for sub-headings (like "Organic content")
                        section_heading = section.select_one('h2, h3, h4, .a-text-bold, [class*="heading"]')
                        if section_heading:
                            heading_text = section_heading.get_text(strip=True)
                            heading_lower = heading_text.lower()
                            
                            # Skip main heading and generic text
                            if heading_lower in ['sustainability features', 'climate pledge friendly']:
                                continue
                            
                            # Check if it's a relevant heading (organic, content, certified, etc.)
                            if any(keyword in heading_lower for keyword in ['organic', 'content', 'certified', 'sustainability']):
                                if heading_text not in seen_texts:
                                    seen_texts.add(heading_text.lower())
                                    feature_parts.append(f"\n{heading_text}")
                                
                                # Get paragraphs after this heading
                                for p in section.select('p'):
                                    p_text = p.get_text(strip=True)
                                    if p_text and len(p_text) > 10:
                                        # Include short descriptions, skip very long ones
                                        if len(p_text) < 500:
                                            p_normalized = p_text.lower().strip()
                                            if p_normalized not in seen_texts:
                                                seen_texts.add(p_normalized)
                                                feature_parts.append(p_text)
                    
                    # Look for certification badges (like "USDA Organic") - add after content sections
                    # Check if we have "Organic content" section - if yes, add certification after it
                    has_organic_content = any('organic content' in part.lower() for part in feature_parts)
                    
                    attribute_pills = element.select('.cpf-dpx-attribute-pill-text span, [class*="attribute-pill"] span')
                    for pill in attribute_pills:
                        pill_text = pill.get_text(strip=True)
                        pill_lower = pill_text.lower()
                        if pill_text and pill_lower not in ['sustainability features', 'sustainability']:
                            # Check if this certification is already mentioned in seen_texts
                            if pill_lower in seen_texts:
                                continue
                            
                            # Check if it's a certification badge (USDA Organic, etc.)
                            if 'organic' in pill_lower or 'certified' in pill_lower or 'usda' in pill_lower:
                                seen_texts.add(pill_lower)
                                # If we have "Organic content" section, add "As certified by" after it
                                if has_organic_content:
                                    # Find the last paragraph and add certification after it
                                    feature_parts.append(f"\nAs certified by {pill_text}")
                                else:
                                    # Just add the certification
                                    feature_parts.append(f"\n{pill_text}")
                    
                    # If we found structured content, use it
                    if feature_parts:
                        text = '\n'.join(feature_parts)
                    else:
                        # Fallback: get all text but remove headings and footers
                        # Remove h2 "Sustainability features"
                        for h2 in element.select('h2'):
                            h2_text = h2.get_text(strip=True).lower()
                            if 'sustainability features' in h2_text:
                                h2.decompose()
                        text = element.get_text(separator='\n', strip=True)
                else:  # Selenium
                    try:
                        # Remove h2 "Sustainability features"
                        h2_elements = element.find_elements(By.CSS_SELECTOR, 'h2')
                        for h2 in h2_elements:
                            h2_text = h2.text.strip().lower()
                            if 'sustainability features' in h2_text:
                                element.execute_script("arguments[0].remove();", h2)
                        
                        # Remove footers
                        footers = element.find_elements(By.CSS_SELECTOR, 'footer, .cpf-dpx-footer, .cpf-dpx-sticky-footer')
                        for footer in footers:
                            footer_text = footer.text.strip().lower()
                            if 'discover more' in footer_text or 'learn more' in footer_text or 'climate pledge friendly' in footer_text:
                                element.execute_script("arguments[0].remove();", footer)
                    except:
                        pass
                    text = element.text.strip()
                
                text = clean_html_tags(text)
                text = filter_ad_phrases(text)
                
                # Remove duplicate phrases and clean up
                # Remove "Sustainability features" if it appears multiple times
                text = re.sub(r'Sustainability features\s*', '', text, flags=re.IGNORECASE)
                text = re.sub(r'(Previous page|Next page|Discover more products with sustainability features\.?\s*Learn more|CLIMATE PLEDGE FRIENDLY)', '', text, flags=re.IGNORECASE)
                text = re.sub(r'\n\s*\n+', '\n', text)  # Clean up multiple newlines
                text = re.sub(r'^\s+|\s+$', '', text, flags=re.MULTILINE)  # Trim each line
                text = text.strip()
                
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
                            # Get key text and clean it (remove colon, invisible chars, extra spaces)
                            key_text = bold_span.get_text()
                            # Remove invisible RTL markers (‏, ‎) and normalize whitespace
                            key_text = re.sub(r'[\u200E\u200F]', '', key_text)  # Remove RTL markers
                            key_text = re.sub(r'\s*:\s*', '', key_text)  # Remove colon and spaces around it
                            key = clean_html_tags(key_text.strip())
                            # Get all text after bold span
                            bold_span.extract()  # Remove bold span to get remaining text
                            value = clean_html_tags(list_item.get_text(separator=' ', strip=True))
                        else:
                            # Fallback: try to split by colon
                            text = list_item.get_text()
                            # Remove invisible RTL markers
                            text = re.sub(r'[\u200E\u200F]', '', text)
                            text = clean_html_tags(text.strip())
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
                        text = bullet.get_text()
                        # Remove invisible RTL markers
                        text = re.sub(r'[\u200E\u200F]', '', text)
                        text = clean_html_tags(text.strip())
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
                            # Get key text and clean it (remove colon, invisible chars, extra spaces)
                            key_text = bold_span.text
                            # Remove invisible RTL markers (‏, ‎) and normalize whitespace
                            key_text = re.sub(r'[\u200E\u200F]', '', key_text)  # Remove RTL markers
                            key_text = re.sub(r'\s*:\s*', '', key_text)  # Remove colon and spaces around it
                            key = clean_html_tags(key_text.strip())
                            # Get all text from list_item, then remove bold text
                            full_text = list_item.text.strip()
                            bold_text = bold_span.text.strip()
                            value = full_text.replace(bold_text, '', 1).strip()
                            # Clean value from invisible chars
                            value = re.sub(r'[\u200E\u200F]', '', value)
                            value = clean_html_tags(value.strip())
                        except:
                            # Fallback: split by colon
                            text = list_item.text
                            # Remove invisible RTL markers
                            text = re.sub(r'[\u200E\u200F]', '', text)
                            text = clean_html_tags(text.strip())
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
                        text = bullet.text
                        # Remove invisible RTL markers
                        text = re.sub(r'[\u200E\u200F]', '', text)
                        text = clean_html_tags(text.strip())
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

