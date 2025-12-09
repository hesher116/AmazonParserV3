"""Browser pool management for Amazon Parser"""
import random
import time
import subprocess
import platform
import re
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
    
    def _get_chrome_version(self) -> Optional[int]:
        """
        Get Chrome browser version (major version number).
        
        Returns:
            Major version number (e.g., 142) or None if cannot determine
        """
        try:
            if platform.system() == 'Windows':
                # Try to get version from registry
                try:
                    import winreg
                    key = winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER,
                        r"Software\Google\Chrome\BLBeacon"
                    )
                    version = winreg.QueryValueEx(key, "version")[0]
                    winreg.CloseKey(key)
                    # Extract major version (e.g., "142.0.7444.176" -> 142)
                    match = re.search(r'^(\d+)', version)
                    if match:
                        return int(match.group(1))
                except ImportError:
                    # winreg not available (shouldn't happen on Windows, but just in case)
                    pass
                except Exception:
                    # Registry method failed, try executable
                    pass
                
                # Try alternative method: check Chrome executable
                chrome_paths = [
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                ]
                for chrome_path in chrome_paths:
                    try:
                        result = subprocess.run(
                            [chrome_path, '--version'],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result.returncode == 0:
                            match = re.search(r'(\d+)\.\d+\.\d+', result.stdout)
                            if match:
                                return int(match.group(1))
                    except Exception:
                        continue
            else:
                # Linux/Mac: use command line
                try:
                    result = subprocess.run(
                        ['google-chrome', '--version'],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        match = re.search(r'(\d+)\.\d+\.\d+', result.stdout)
                        if match:
                            return int(match.group(1))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Could not determine Chrome version: {e}")
        
        return None
    
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
        
        # Force US locale for Amazon (to get USD prices instead of EUR)
        # Accept-Language header will be set via Chrome preferences
        prefs = {
            'intl.accept_languages': 'en-US,en;q=0.9',
        }
        options.add_experimental_option('prefs', prefs)
        
        # Headless mode if configured
        if Settings.HEADLESS:
            options.add_argument('--headless=new')
            # Additional options for better headless compatibility
            options.add_argument('--disable-software-rasterizer')
            options.add_argument('--disable-extensions')
            options.add_argument('--disable-background-timer-throttling')
            options.add_argument('--disable-backgrounding-occluded-windows')
            options.add_argument('--disable-renderer-backgrounding')
            # Ensure JavaScript executes properly in headless mode
            options.add_argument('--enable-javascript')
        
        # Set page load strategy to "none" for faster navigation
        # This allows us to start interacting with page before it fully loads
        options.page_load_strategy = 'none'
        
        # IMPORTANT: Do NOT block images - we need them for parsing!
        # Images (image/png, image/jpeg, image/webp) will load normally
        
        try:
            # Try to get Chrome version to ensure ChromeDriver compatibility
            chrome_version = self._get_chrome_version()
            if chrome_version:
                logger.info(f"Detected Chrome version: {chrome_version}")
                # Let undetected_chromedriver automatically download matching ChromeDriver
                # by passing version_main parameter
                self._driver = uc.Chrome(options=options, version_main=chrome_version)
            else:
                # If we can't determine version, let undetected_chromedriver auto-detect
                logger.info("Auto-detecting Chrome version for ChromeDriver...")
                self._driver = uc.Chrome(options=options)
            
            # With page_load_strategy="none", we don't need long timeout
            self._driver.set_page_load_timeout(30)  # Fallback timeout
            self._driver.implicitly_wait(0.5)  # Reduced implicit wait for faster fallback
            
            # Set window size explicitly
            self._driver.set_window_size(Settings.WINDOW_WIDTH, Settings.WINDOW_HEIGHT)
            
            logger.info(f"Browser initialized (headless: {Settings.HEADLESS})")
            return self._driver
            
        except WebDriverException as e:
            error_msg = str(e)
            # If version mismatch error, try without version_main to let library auto-detect
            if "version" in error_msg.lower() or "chrome version" in error_msg.lower():
                logger.warning("Version mismatch detected, retrying with auto-detection...")
                try:
                    # Clear any cached driver
                    self._driver = None
                    # Retry without version_main to let undetected_chromedriver auto-detect
                    self._driver = uc.Chrome(options=options)
                    self._driver.set_page_load_timeout(30)
                    self._driver.implicitly_wait(0.5)
                    self._driver.set_window_size(Settings.WINDOW_WIDTH, Settings.WINDOW_HEIGHT)
                    logger.info(f"Browser initialized with auto-detection (headless: {Settings.HEADLESS})")
                    return self._driver
                except Exception as retry_error:
                    logger.error(f"Retry failed: {retry_error}")
                    raise
            else:
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
    
    def navigate_to(self, url: str, need_images: bool = False) -> bool:
        """
        Navigate to URL with error handling.
        
        Args:
            url: URL to navigate to
            need_images: If True, wait for gallery elements to load
            
        Returns:
            True if navigation successful
        """
        driver = self.get_driver()
        
        try:
            logger.info(f"Navigating to: {url[:80]}...")
            import time
            from utils.text_utils import normalize_amazon_url
            
            start_time = time.time()
            
            # Normalize URL to clean format: https://www.amazon.com/dp/{ASIN}/&language=en_US&currency=USD
            normalized_url = normalize_amazon_url(url)
            
            # Set cookies for US locale before navigation (Amazon uses cookies to determine locale)
            # This ensures we get USD prices instead of EUR
            try:
                # Navigate to Amazon.com first to set cookies (if not already on Amazon)
                if 'amazon.com' not in driver.current_url:
                    driver.get('https://www.amazon.com')
                    # Small wait for page to load
                    time.sleep(0.5)
                
                # Set locale cookies for US
                driver.add_cookie({
                    'name': 'i18n-prefs',
                    'value': 'USD',
                    'domain': '.amazon.com',
                    'path': '/',
                })
                driver.add_cookie({
                    'name': 'lc-main',
                    'value': 'en_US',
                    'domain': '.amazon.com',
                    'path': '/',
                })
                logger.debug("US locale cookies set")
            except Exception as e:
                logger.debug(f"Could not set locale cookies (will use URL parameters): {e}")
            
            # Navigate with page_load_strategy="none" - won't wait for full page load
            # Use normalized URL which already has locale parameters
            try:
                driver.get(normalized_url)
            except Exception as e:
                # With page_load_strategy="none", get() may raise exception but page still loads
                logger.debug(f"  [Navigation] get() completed (expected with page_load_strategy='none'): {e}")
            
            init_time = time.time() - start_time
            logger.info(f"  [Navigation] Navigation initiated ({init_time:.2f}s)")
            
            # Wait for gallery elements only if images are needed
            if need_images:
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
                    wait = WebDriverWait(driver, 3)  # Max 3 seconds for gallery (optimized)
                    
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
                                    break  # Count each selector once
                        except:
                            pass
                    
                    logger.info(f"  [Navigation] Found {valid_images} images with valid sources")
                    
                except TimeoutException:
                    logger.warning(f"  [Navigation] Gallery elements timeout after 3s, continuing anyway...")
            else:
                logger.debug(f"  [Navigation] Skipping gallery wait (images not needed)")
            
            # No delays needed - DOM dump will be saved after waiting for elements to load
            # All parsing happens on local DOM dump, so delays here just slow things down
            
            # Handle soft blocks (including "Continue shopping" button) - with timeout
            soft_block_start = time.time()
            try:
                # Quick check with timeout to avoid long waits
                if self._handle_soft_block_quick():
                    soft_block_time = time.time() - soft_block_start
                    logger.info(f"  [Navigation] Handled soft block ({soft_block_time:.2f}s)")
                else:
                    soft_block_time = time.time() - soft_block_start
                    logger.debug(f"  [Navigation] Soft block check: {soft_block_time:.2f}s")
            except Exception as e:
                logger.debug(f"  [Navigation] Soft block check error: {e}")
            
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
        return self._handle_soft_block_quick()
    
    def _handle_soft_block_quick(self) -> bool:
        """
        Quick check for soft blocks with minimal delay.
        
        Returns:
            True if block was handled
        """
        driver = self.get_driver()
        
        try:
            # Quick check for "Continue shopping" button (most common selectors first)
            continue_selectors = [
                "//a[contains(text(), 'Continue shopping')]",
                "//button[contains(text(), 'Continue shopping')]",
            ]
            
            for selector in continue_selectors:
                try:
                    continue_buttons = driver.find_elements(By.XPATH, selector)
                    if continue_buttons:
                        for btn in continue_buttons:
                            if btn.is_displayed():
                                logger.info("Found 'Continue shopping' button, clicking...")
                                btn.click()
                                # Wait for button to disappear or page to change (max 1 second)
                                try:
                                    wait = WebDriverWait(driver, 1)
                                    wait.until(lambda d: not btn.is_displayed() or d.execute_script("return document.readyState") == 'complete')
                                except TimeoutException:
                                    # Button might still be visible but action completed, continue
                                    logger.debug("Button visibility wait timeout (action may have completed)")
                                return True
                except:
                    continue
            
            # Quick CAPTCHA check
            try:
                captcha_elements = driver.find_elements(
                    By.XPATH,
                    "//*[contains(text(), 'Enter the characters')]"
                )
                if captcha_elements:
                    logger.warning("CAPTCHA detected! Manual intervention may be required.")
                    return False
            except:
                pass
            
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
        Scroll element into view and wait for it to be visible.
        
        Args:
            element: WebElement to scroll to
            
        Returns:
            True if successful
        """
        driver = self.get_driver()
        
        try:
            # Get element location before scroll
            initial_location = element.location_once_scrolled_into_view
            
            driver.execute_script(
                "arguments[0].scrollIntoView({behavior: 'smooth', block: 'center'});",
                element
            )
            
            # Wait for element to be visible in viewport (max 2 seconds)
            try:
                wait = WebDriverWait(driver, 2)
                wait.until(EC.visibility_of(element))
            except TimeoutException:
                # If timeout, element might already be visible, continue
                logger.debug("Element visibility wait timeout (may already be visible)")
            
            return True
        except Exception as e:
            logger.debug(f"Scroll failed: {e}")
            return False
    
    def scroll_page(self, direction: str = 'down', amount: int = 500):
        """
        Scroll page in specified direction and wait for scroll to complete.
        
        Args:
            direction: 'up' or 'down'
            amount: Pixels to scroll
        """
        driver = self.get_driver()
        
        try:
            # Get initial scroll position
            initial_scroll = driver.execute_script("return window.pageYOffset;")
            
            if direction == 'down':
                driver.execute_script(f"window.scrollBy(0, {amount});")
            else:
                driver.execute_script(f"window.scrollBy(0, -{amount});")
            
            # Wait for scroll to complete (check if scroll position changed, max 1 second)
            try:
                wait = WebDriverWait(driver, 1)
                wait.until(lambda d: abs(d.execute_script("return window.pageYOffset;") - initial_scroll) >= amount * 0.5)
            except TimeoutException:
                # Scroll might have completed instantly or was blocked, continue
                logger.debug("Scroll position wait timeout (scroll may have completed)")
        except Exception as e:
            logger.debug(f"Scroll failed: {e}")
    
    def click_element(self, element, wait_for_change: bool = True, change_selector: str = None) -> bool:
        """
        Click element and optionally wait for DOM change.
        
        Args:
            element: WebElement to click
            wait_for_change: If True, wait for DOM to change after click (default: True)
            change_selector: CSS selector to wait for after click (optional)
            
        Returns:
            True if successful
        """
        driver = self.get_driver()
        
        try:
            self.scroll_to_element(element)
            
            # Get initial DOM state if we need to wait for change
            initial_html = None
            if wait_for_change:
                try:
                    initial_html = driver.execute_script("return document.body.innerHTML.length;")
                except:
                    pass
            
            element.click()
            
            # Wait for DOM change if requested (max 1 second)
            if wait_for_change:
                try:
                    wait = WebDriverWait(driver, 1)
                    if change_selector:
                        # Wait for specific element to appear
                        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, change_selector)))
                    elif initial_html is not None:
                        # Wait for DOM to change
                        wait.until(lambda d: d.execute_script("return document.body.innerHTML.length;") != initial_html)
                except TimeoutException:
                    # DOM might not change or change was instant, continue
                    logger.debug("DOM change wait timeout (change may have been instant)")
            
            return True
        except Exception as e:
            # Try JavaScript click as fallback
            try:
                driver.execute_script("arguments[0].click();", element)
                # No delay needed - if JS click works, it's instant
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

