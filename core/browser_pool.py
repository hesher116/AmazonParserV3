"""Browser pool management for Amazon Parser"""
import random
import time
from typing import Optional

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

from config.settings import Settings
from utils.logger import get_logger

logger = get_logger(__name__)


class BrowserPool:
    """Manages browser instances with anti-detection measures."""
    
    def __init__(self):
        self._driver: Optional[uc.Chrome] = None
        self._user_agent: str = random.choice(Settings.USER_AGENTS)
    
    def get_driver(self) -> uc.Chrome:
        """
        Get or create a browser driver instance.
        
        Returns:
            Configured Chrome driver
        """
        if self._driver is not None:
            return self._driver
        
        logger.info("Initializing browser driver...")
        
        options = uc.ChromeOptions()
        
        # Anti-detection options
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-gpu')
        options.add_argument('--lang=en-US')
        options.add_argument('--disable-notifications')
        options.add_argument('--disable-popup-blocking')
        options.add_argument(f'--window-size={Settings.WINDOW_WIDTH},{Settings.WINDOW_HEIGHT}')
        
        # Set user agent
        options.add_argument(f'--user-agent={self._user_agent}')
        
        # Headless mode if configured
        if Settings.HEADLESS:
            options.add_argument('--headless=new')
        
        # Set page load strategy to "none" for faster navigation
        # This allows us to start interacting with page before it fully loads
        options.page_load_strategy = 'none'
        
        # IMPORTANT: Do NOT block images - we need them for parsing!
        # Images (image/png, image/jpeg, image/webp) will load normally
        
        try:
            self._driver = uc.Chrome(options=options)
            # With page_load_strategy="none", we don't need long timeout
            self._driver.set_page_load_timeout(30)  # Fallback timeout
            self._driver.implicitly_wait(2)  # Reduced implicit wait
            
            # Set window size explicitly
            self._driver.set_window_size(Settings.WINDOW_WIDTH, Settings.WINDOW_HEIGHT)
            
            logger.info(f"Browser initialized (headless: {Settings.HEADLESS})")
            return self._driver
            
        except WebDriverException as e:
            logger.error(f"Failed to initialize browser: {e}")
            raise
    
    def close_driver(self):
        """Close the browser driver."""
        if self._driver is not None:
            try:
                # Try graceful shutdown first
                try:
                    self._driver.quit()
                except Exception:
                    # If quit fails, try close
                    try:
                        self._driver.close()
                    except Exception:
                        pass
                logger.info("Browser closed")
            except Exception as e:
                logger.warning(f"Error closing browser: {e}")
            finally:
                self._driver = None
    
    def navigate_to(self, url: str) -> bool:
        """
        Navigate to URL with error handling.
        
        Args:
            url: URL to navigate to
            
        Returns:
            True if navigation successful
        """
        driver = self.get_driver()
        
        try:
            logger.info(f"Navigating to: {url[:80]}...")
            import time
            start_time = time.time()
            
            # Navigate with page_load_strategy="none" - won't wait for full page load
            try:
                driver.get(url)
            except Exception as e:
                # With page_load_strategy="none", get() may raise exception but page still loads
                logger.debug(f"  [Navigation] get() completed (expected with page_load_strategy='none'): {e}")
            
            init_time = time.time() - start_time
            logger.info(f"  [Navigation] Navigation initiated ({init_time:.2f}s)")
            
            # Wait specifically for gallery image elements (what we actually need)
            # These are the critical elements for image parsing
            gallery_selectors = [
                "#landingImage",  # Main hero image
                "#imgTagWrapperId img",  # Image wrapper
                "#altImages img",  # Gallery thumbnails
            ]
            
            logger.info(f"  [Navigation] Waiting for gallery elements...")
            wait_start = time.time()
            
            try:
                wait = WebDriverWait(driver, 6)  # Max 6 seconds for gallery
                
                # Wait for at least one gallery element to appear
                def gallery_ready(driver):
                    """Check if gallery elements are present and have valid image sources."""
                    for selector in gallery_selectors:
                        try:
                            elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            for elem in elements:
                                # Check if element has valid src or data-old-hires
                                src = elem.get_attribute('src') or elem.get_attribute('data-old-hires') or elem.get_attribute('data-src')
                                if src and src.startswith('http') and 'data:image' not in src:
                                    # Valid image source found
                                    return True
                        except:
                            continue
                    return False
                
                wait.until(gallery_ready)
                gallery_time = time.time() - wait_start
                logger.info(f"  [Navigation] Gallery elements ready ({gallery_time:.2f}s)")
                
                # Verify images have valid sources
                valid_images = 0
                for selector in gallery_selectors:
                    try:
                        elements = driver.find_elements(By.CSS_SELECTOR, selector)
                        for elem in elements:
                            src = elem.get_attribute('src') or elem.get_attribute('data-old-hires') or elem.get_attribute('data-src')
                            if src and src.startswith('http') and 'data:image' not in src:
                                valid_images += 1
                    except:
                        pass
                
                logger.info(f"  [Navigation] Found {valid_images} images with valid sources")
                
            except TimeoutException:
                logger.warning(f"  [Navigation] Gallery elements timeout after 6s, continuing anyway...")
            
            # Small delay to let images start loading
            self._random_sleep(0.3, 0.6)
            
            # Handle soft blocks (including "Continue shopping" button)
            if self._handle_soft_block():
                logger.info("  [Navigation] Handled soft block, continuing...")
            
            total_time = time.time() - start_time
            logger.info(f"  [Navigation] Navigation complete (total: {total_time:.2f}s)")
            
            # Warn if navigation took too long
            if total_time > 6:
                logger.warning(f"  [Navigation] Navigation took {total_time:.2f}s (target: 3-6s)")
            elif total_time < 3:
                logger.debug(f"  [Navigation] Fast navigation: {total_time:.2f}s")
            
            return True
            
        except TimeoutException:
            logger.error("Page load timeout")
            return False
        except WebDriverException as e:
            logger.error(f"Navigation failed: {e}")
            return False
    
    def _random_sleep(self, min_sec: float = None, max_sec: float = None):
        """
        Random sleep to mimic human behavior.
        
        Args:
            min_sec: Minimum sleep time (default from settings)
            max_sec: Maximum sleep time (default from settings)
        """
        min_sec = min_sec or Settings.RATE_LIMIT_MIN
        max_sec = max_sec or Settings.RATE_LIMIT_MAX
        
        sleep_time = random.uniform(min_sec, max_sec)
        time.sleep(sleep_time)
    
    def _handle_soft_block(self) -> bool:
        """
        Handle Amazon soft blocks (CAPTCHA, "Continue shopping" button).
        
        Returns:
            True if block was handled
        """
        driver = self.get_driver()
        
        try:
            # Check for "Continue shopping" button (multiple possible selectors)
            continue_selectors = [
                "//a[contains(text(), 'Continue shopping')]",
                "//button[contains(text(), 'Continue shopping')]",
                "//a[contains(@class, 'continue-shopping')]",
                "//button[contains(@class, 'continue-shopping')]",
                "//a[contains(., 'Continue shopping')]",
            ]
            
            for selector in continue_selectors:
                try:
                    continue_buttons = driver.find_elements(By.XPATH, selector)
                    if continue_buttons:
                        for btn in continue_buttons:
                            if btn.is_displayed():
                                logger.info("Found 'Continue shopping' button, clicking...")
                                btn.click()
                                self._random_sleep(0.5, 1.0)
                                return True
                except:
                    continue
            
            # Check for CAPTCHA
            captcha_elements = driver.find_elements(
                By.XPATH,
                "//*[contains(text(), 'Enter the characters')]"
            )
            if captcha_elements:
                logger.warning("CAPTCHA detected! Manual intervention may be required.")
                return False
            
            return False
            
        except Exception as e:
            logger.debug(f"Soft block check error: {e}")
            return False
    
    def wait_for_element(
        self, 
        by: By, 
        value: str, 
        timeout: int = None
    ) -> Optional[object]:
        """
        Wait for element to be present.
        
        Args:
            by: Locator strategy
            value: Locator value
            timeout: Wait timeout (default from settings)
            
        Returns:
            WebElement or None
        """
        driver = self.get_driver()
        timeout = timeout or Settings.TIMEOUT
        
        try:
            element = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return element
        except TimeoutException:
            logger.debug(f"Element not found: {by}={value}")
            return None
    
    def wait_for_elements(
        self, 
        by: By, 
        value: str, 
        timeout: int = None
    ) -> list:
        """
        Wait for elements to be present.
        
        Args:
            by: Locator strategy
            value: Locator value
            timeout: Wait timeout (default from settings)
            
        Returns:
            List of WebElements
        """
        driver = self.get_driver()
        timeout = timeout or Settings.TIMEOUT
        
        try:
            WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((by, value))
            )
            return driver.find_elements(by, value)
        except TimeoutException:
            logger.debug(f"Elements not found: {by}={value}")
            return []
    
    def scroll_to_element(self, element) -> bool:
        """
        Scroll element into view.
        
        Args:
            element: WebElement to scroll to
            
        Returns:
            True if successful
        """
        driver = self.get_driver()
        
        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
                element
            )
            self._random_sleep(0.5, 1.0)
            return True
        except Exception as e:
            logger.debug(f"Scroll failed: {e}")
            return False
    
    def scroll_page(self, direction: str = 'down', amount: int = 500):
        """
        Scroll page in specified direction.
        
        Args:
            direction: 'up' or 'down'
            amount: Pixels to scroll
        """
        driver = self.get_driver()
        
        try:
            if direction == 'down':
                driver.execute_script(f"window.scrollBy(0, {amount});")
            else:
                driver.execute_script(f"window.scrollBy(0, -{amount});")
            
            self._random_sleep(0.3, 0.7)
        except Exception as e:
            logger.debug(f"Scroll failed: {e}")
    
    def click_element(self, element, min_delay: float = None, max_delay: float = None) -> bool:
        """
        Click element with error handling.
        
        Args:
            element: WebElement to click
            min_delay: Minimum delay after click (default: 0.1)
            max_delay: Maximum delay after click (default: 0.3)
            
        Returns:
            True if successful
        """
        driver = self.get_driver()
        
        try:
            self.scroll_to_element(element)
            element.click()
            # Use minimal delay for thumbnail clicks
            min_delay = min_delay if min_delay is not None else 0.1
            max_delay = max_delay if max_delay is not None else 0.3
            self._random_sleep(min_delay, max_delay)
            return True
        except Exception as e:
            # Try JavaScript click as fallback
            try:
                driver.execute_script("arguments[0].click();", element)
                self._random_sleep()
                return True
            except Exception:
                logger.debug(f"Click failed: {e}")
                return False
    
    def get_page_source(self) -> str:
        """Get current page source."""
        return self.get_driver().page_source
    
    def get_current_url(self) -> str:
        """Get current URL."""
        return self.get_driver().current_url
    
    def take_screenshot(self, filename: str) -> bool:
        """
        Take screenshot of current page.
        
        Args:
            filename: Path to save screenshot
            
        Returns:
            True if successful
        """
        try:
            self.get_driver().save_screenshot(filename)
            logger.info(f"Screenshot saved: {filename}")
            return True
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return False
    
    def close_modal(self) -> bool:
        """
        Try to close any modal/popup on the page.
        
        Returns:
            True if modal was closed
        """
        driver = self.get_driver()
        
        # Common close button selectors
        close_selectors = [
            "//button[@aria-label='Close']",
            "//button[contains(@class, 'close')]",
            "//span[contains(@class, 'close')]",
            "//div[@data-action='a-popover-close']",
            "//button[@data-action='a-modal-close']",
        ]
        
        for selector in close_selectors:
            try:
                elements = driver.find_elements(By.XPATH, selector)
                for element in elements:
                    if element.is_displayed():
                        element.click()
                        self._random_sleep(0.3, 0.5)
                        logger.debug("Closed modal")
                        return True
            except Exception:
                continue
        
        return False

