"""Text utilities for Amazon Parser"""
import re
from typing import Dict, List, Optional
from bs4 import BeautifulSoup

from config.settings import Settings
from utils.logger import get_logger

logger = get_logger(__name__)


def clean_html_tags(text: str) -> str:
    """
    Remove HTML tags from text.
    
    Args:
        text: Text with potential HTML tags
        
    Returns:
        Clean text without HTML tags
    """
    if not text or not isinstance(text, str):
        return ''
    
    # If text doesn't look like HTML, return as is
    if '<' not in text and '>' not in text:
        return text.strip()
    
    try:
        # Use BeautifulSoup to handle HTML properly
        soup = BeautifulSoup(text, 'html.parser')
        clean_text = soup.get_text(separator=' ')
        
        # Clean up whitespace
        clean_text = re.sub(r'\s+', ' ', clean_text)
        clean_text = clean_text.strip()
        
        return clean_text
    except Exception as e:
        # If BeautifulSoup fails, use regex fallback
        logger.debug(f"BeautifulSoup failed, using regex fallback: {e}")
        clean_text = re.sub(r'<[^>]+>', '', text)
        clean_text = re.sub(r'\s+', ' ', clean_text)
        return clean_text.strip()


def filter_ad_phrases(text: str) -> str:
    """
    Filter out advertising phrases from text.
    
    Args:
        text: Original text
        
    Returns:
        Text with ad phrases removed
    """
    if not text:
        return ''
    
    filtered_text = text
    for phrase in Settings.AD_PHRASES:
        # Case-insensitive removal
        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
        filtered_text = pattern.sub('', filtered_text)
    
    # Clean up resulting whitespace
    filtered_text = re.sub(r'\s+', ' ', filtered_text)
    filtered_text = filtered_text.strip()
    
    return filtered_text


def extract_table_data(element) -> Dict[str, str]:
    """
    Extract data from HTML table element.
    
    Args:
        element: Selenium WebElement or BeautifulSoup element
        
    Returns:
        Dictionary with table data
    """
    result = {}
    
    if element is None:
        return result
    
    try:
        # If element is already BeautifulSoup, use it directly
        if hasattr(element, 'find_all') and hasattr(element, 'prettify'):
            # Already a BeautifulSoup element
            soup = element
        elif hasattr(element, 'get_attribute'):
            # Selenium WebElement
            html = element.get_attribute('outerHTML')
            if not html or not isinstance(html, str):
                return result
            soup = BeautifulSoup(html, 'html.parser')
        else:
            # Try to convert to string and parse
            html = str(element) if element else ''
            if not html:
                return result
            soup = BeautifulSoup(html, 'html.parser')
        
        # Try to find table rows
        rows = soup.find_all('tr')
        for row in rows:
            if row is None:
                continue
            try:
                cells = row.find_all(['th', 'td'])
                if len(cells) >= 2:
                    cell0 = cells[0]
                    cell1 = cells[1]
                    if cell0 is not None and cell1 is not None:
                        try:
                            # BeautifulSoup elements always have get_text()
                            if hasattr(cell0, 'get_text'):
                                key_text = cell0.get_text(strip=True) or ''
                            else:
                                key_text = str(cell0) if cell0 else ''
                            
                            if hasattr(cell1, 'get_text'):
                                value_text = cell1.get_text(strip=True) or ''
                            else:
                                value_text = str(cell1) if cell1 else ''
                            
                            key = clean_html_tags(key_text)
                            value = clean_html_tags(value_text)
                            if key and value:
                                result[key] = value
                        except (AttributeError, TypeError, Exception) as e:
                            logger.debug(f"Error extracting cell data: {e}")
                            continue
            except Exception as e:
                logger.debug(f"Error processing row: {e}")
                continue
        
        # Also try definition lists
        dts = soup.find_all('dt')
        dds = soup.find_all('dd')
        for dt, dd in zip(dts, dds):
            if dt is None or dd is None:
                continue
            try:
                if hasattr(dt, 'get_text'):
                    dt_text = dt.get_text(strip=True) or ''
                else:
                    dt_text = str(dt) if dt else ''
                
                if hasattr(dd, 'get_text'):
                    dd_text = dd.get_text(strip=True) or ''
                else:
                    dd_text = str(dd) if dd else ''
                
                key = clean_html_tags(dt_text)
                value = clean_html_tags(dd_text)
                if key and value:
                    result[key] = value
            except (AttributeError, TypeError, Exception) as e:
                logger.debug(f"Error extracting dt/dd data: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Failed to extract table data: {e}")
    
    return result


def extract_list_items(element) -> List[str]:
    """
    Extract items from HTML list element.
    
    Args:
        element: Selenium WebElement or BeautifulSoup element
        
    Returns:
        List of text items
    """
    items = []
    
    if element is None:
        return items
    
    try:
        # If element is already BeautifulSoup, use it directly
        if hasattr(element, 'find_all') and hasattr(element, 'prettify'):
            # Already a BeautifulSoup element
            soup = element
        elif hasattr(element, 'get_attribute'):
            # Selenium WebElement
            html = element.get_attribute('outerHTML')
            if not html or not isinstance(html, str):
                return items
            soup = BeautifulSoup(html, 'html.parser')
        else:
            # Try to convert to string and parse
            html = str(element) if element else ''
            if not html:
                return items
            soup = BeautifulSoup(html, 'html.parser')
        
        # Find list items
        li_elements = soup.find_all('li')
        for li in li_elements:
            if li is None:
                continue
            try:
                # BeautifulSoup elements always have get_text()
                if hasattr(li, 'get_text'):
                    li_text = li.get_text(strip=True) or ''
                else:
                    li_text = str(li) if li else ''
                
                text = clean_html_tags(li_text)
                text = filter_ad_phrases(text)
                if text:
                    items.append(text)
            except (AttributeError, TypeError, Exception) as e:
                logger.debug(f"Error extracting list item: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Failed to extract list items: {e}")
    
    return items


def parse_price(price_text: str) -> Dict[str, Optional[str]]:
    """
    Parse price text into structured format.
    
    Args:
        price_text: Price text (e.g., "$19.99" or "$19.99 $29.99")
        
    Returns:
        Dictionary with current_price and original_price
    """
    result = {
        'current_price': None,
        'original_price': None,
        'currency': 'USD'
    }
    
    if not price_text:
        return result
    
    # Find all prices in text
    price_pattern = r'\$[\d,]+\.?\d*'
    prices = re.findall(price_pattern, price_text)
    
    if prices:
        result['current_price'] = prices[0]
        if len(prices) > 1:
            result['original_price'] = prices[1]
    
    return result


def parse_rating(rating_text: str) -> Dict[str, Optional[str]]:
    """
    Parse rating text into structured format.
    
    Args:
        rating_text: Rating text (e.g., "4.5 out of 5 stars")
        
    Returns:
        Dictionary with rating value and count
    """
    result = {
        'rating': None,
        'max_rating': '5',
        'rating_count': None
    }
    
    if not rating_text:
        return result
    
    # Find rating value
    rating_pattern = r'(\d+\.?\d*)\s*(?:out of|\/)\s*(\d+)'
    match = re.search(rating_pattern, rating_text)
    if match:
        result['rating'] = match.group(1)
        result['max_rating'] = match.group(2)
    
    # Find rating count
    count_pattern = r'([\d,]+)\s*(?:ratings?|reviews?)'
    match = re.search(count_pattern, rating_text, re.IGNORECASE)
    if match:
        result['rating_count'] = match.group(1).replace(',', '')
    
    return result


def extract_asin_from_url(url: str) -> Optional[str]:
    """
    Extract ASIN from Amazon product URL.
    
    Args:
        url: Amazon product URL
        
    Returns:
        ASIN or None
    """
    # Common ASIN patterns in URLs
    patterns = [
        r'/dp/([A-Z0-9]{10})',
        r'/gp/product/([A-Z0-9]{10})',
        r'/product/([A-Z0-9]{10})',
        r'asin=([A-Z0-9]{10})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    
    return None


def normalize_whitespace(text: str) -> str:
    """
    Normalize whitespace in text.
    
    Args:
        text: Original text
        
    Returns:
        Text with normalized whitespace
    """
    if not text:
        return ''
    
    # Replace various whitespace characters with single space
    text = re.sub(r'[\t\n\r\f\v]+', ' ', text)
    # Replace multiple spaces with single space
    text = re.sub(r' +', ' ', text)
    # Strip leading/trailing whitespace
    text = text.strip()
    
    return text

