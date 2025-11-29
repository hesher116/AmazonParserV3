"""Base class for parsers with DOM dump support"""
from typing import Optional
from bs4 import BeautifulSoup

from core.browser_pool import BrowserPool
from utils.logger import get_logger

logger = get_logger(__name__)


class BaseParser:
    """Base class for all parsers with DOM dump support."""
    
    def __init__(self, browser_pool: BrowserPool, dom_soup: Optional[BeautifulSoup] = None):
        """
        Initialize parser with browser pool and optional DOM soup.
        
        Args:
            browser_pool: Browser pool instance for dynamic content
            dom_soup: BeautifulSoup object with page DOM (for static parsing)
        """
        self.browser = browser_pool
        self.dom_soup = dom_soup
    
    def find_element_by_selector(self, selector: str, use_dom: bool = True):
        """
        Find element by CSS selector, using DOM dump if available.
        
        Args:
            selector: CSS selector
            use_dom: If True, try DOM dump first (faster), then fallback to Selenium
            
        Returns:
            BeautifulSoup element or Selenium WebElement
        """
        # Try DOM dump first if available and requested
        if use_dom and self.dom_soup:
            try:
                element = self.dom_soup.select_one(selector)
                if element:
                    return element
            except Exception as e:
                logger.debug(f"DOM selector failed for {selector}: {e}")
        
        # Fallback to Selenium - log for monitoring
        logger.info(f"⚠️  Fallback to Selenium for selector: {selector[:60]}...")
        try:
            driver = self.browser.get_driver()
            from selenium.webdriver.common.by import By
            element = driver.find_element(By.CSS_SELECTOR, selector)
            logger.debug(f"✓ Selenium found element for: {selector[:60]}...")
            return element
        except Exception as e:
            logger.debug(f"Selenium selector failed for {selector}: {e}")
            return None
    
    def find_elements_by_selector(self, selector: str, use_dom: bool = True):
        """
        Find elements by CSS selector, using DOM dump if available.
        
        Args:
            selector: CSS selector
            use_dom: If True, try DOM dump first (faster), then fallback to Selenium
            
        Returns:
            List of BeautifulSoup elements or Selenium WebElements
        """
        # Try DOM dump first if available and requested
        if use_dom and self.dom_soup:
            try:
                elements = self.dom_soup.select(selector)
                if elements:
                    return list(elements)  # Ensure it's a list
            except Exception as e:
                logger.debug(f"DOM selector failed for {selector}: {e}")
        
        # Fallback to Selenium - log for monitoring
        logger.info(f"⚠️  Fallback to Selenium for selector: {selector[:60]}...")
        try:
            driver = self.browser.get_driver()
            from selenium.webdriver.common.by import By
            elements = driver.find_elements(By.CSS_SELECTOR, selector)
            count = len(elements) if elements else 0
            logger.debug(f"✓ Selenium found {count} elements for: {selector[:60]}...")
            return list(elements) if elements else []
        except Exception as e:
            logger.debug(f"Selenium selector failed for {selector}: {e}")
            return []
    
    def get_text_from_element(self, element) -> str:
        """
        Extract text from element (works with both BeautifulSoup and Selenium).
        
        Args:
            element: BeautifulSoup element or Selenium WebElement
            
        Returns:
            Cleaned text
        """
        if element is None:
            return ''
        
        # BeautifulSoup element
        if hasattr(element, 'get_text'):
            return element.get_text(separator=' ', strip=True)
        
        # Selenium WebElement
        if hasattr(element, 'text'):
            return element.text.strip()
        
        return str(element).strip()
    
    def get_attribute_from_element(self, element, attr: str) -> Optional[str]:
        """
        Get attribute from element (works with both BeautifulSoup and Selenium).
        
        Args:
            element: BeautifulSoup element or Selenium WebElement
            attr: Attribute name
            
        Returns:
            Attribute value or None
        """
        if element is None:
            return None
        
        # BeautifulSoup element
        if hasattr(element, 'get'):
            return element.get(attr)
        
        # Selenium WebElement
        if hasattr(element, 'get_attribute'):
            return element.get_attribute(attr)
        
        return None

