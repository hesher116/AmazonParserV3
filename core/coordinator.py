"""Coordinator - Manages agent execution and results collection"""
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Callable
from pathlib import Path
from collections import defaultdict

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from core.browser_pool import BrowserPool
from core.database import Database
from core.docx_generator import DocxGenerator
from core.parsing_metrics import ParsingMetrics
from agents.hero_parser import HeroParser
from agents.gallery_parser import GalleryParser
from agents.aplus_product_parser import APlusProductParser
from agents.aplus_brand_parser import APlusBrandParser
from agents.aplus_manufacturer_parser import APlusManufacturerParser
from agents.text_parser import TextParserAgent
from agents.reviews_parser import ReviewsParserAgent
from agents.validator import ValidatorAgent
from utils.file_utils import create_output_structure, sanitize_filename
from utils.logger import get_logger
from config.settings import Settings

logger = get_logger(__name__)


class Coordinator:
    """Coordinates agent execution and manages parsing workflow."""
    
    def __init__(self, db: Database):
        self.db = db
        self.browser_pool: Optional[BrowserPool] = None
        self.results: Dict = {}
        self.output_dir: Optional[str] = None
        self.progress_callback: Optional[Callable] = None
        # DOM dump for atomic parsing
        self.dom_dump: Optional[str] = None
        self.dom_soup: Optional[object] = None
        # Selector cache for A+ parsers
        from collections import defaultdict
        self.selector_cache: Dict[str, List[str]] = defaultdict(list) if Settings.SELECTOR_CACHE_ENABLED else {}
        # Performance metrics
        self.performance_metrics: Dict[str, float] = {}
        # Parsing metrics and selector statistics
        self.metrics = ParsingMetrics(max_selector_cache_size=50)
    
    def run_parsing(
        self,
        task_id: int,
        url: str,
        config: Dict,
        progress_callback: Callable = None
    ) -> Dict:
        """
        Run parsing workflow based on configuration.
        
        Args:
            task_id: Database task ID
            url: Amazon product URL
            config: Configuration with selected agents
            progress_callback: Callback function for progress updates
            
        Returns:
            Dictionary with all results
        """
        self.progress_callback = progress_callback
        self.results = {
            'url': url,
            'task_id': task_id,
            'text': {},
            'images': {},
            'reviews': {},
            'qa': {},
            'validation': {},
            'errors': [],
            'output_dir': None,
            'start_time': time.time()  # Track start time for processing duration
        }
        
        try:
            # Update task status
            self.db.update_task(task_id, status='running')
            self._update_progress('Initializing browser...', 5)
            
            # Initialize browser
            self.browser_pool = BrowserPool()
            
            # Navigate to product page
            # Check if images are needed
            need_images = any([
                config.get('images_hero', False),
                config.get('images_gallery', False),
                config.get('images_aplus_product', False),
                config.get('images_aplus_brand', False),
                config.get('images_aplus_manufacturer', False),
            ])
            
            self._update_progress('Loading product page...', 10)
            if not self.browser_pool.navigate_to(url, need_images=need_images):
                raise Exception("Failed to load product page")
            
            # Save DOM dump for atomic parsing (all agents work with same snapshot)
            self._update_progress('Saving page snapshot...', 12)
            self._save_dom_dump()
            
            # Get product name for folder (always needed, but parse full text only if checkbox is checked)
            product_name = None
            if config.get('text', False):
                # Full text parsing
                self._update_progress('Parsing product info...', 15)
                text_agent = TextParserAgent(self.browser_pool, self.dom_soup)
                text_agent.metrics = self.metrics  # Pass metrics to agent
                text_result = self._run_with_retry(text_agent.parse)
                self.results['text'] = text_result
                product_name = text_result.get('title', 'Unknown Product')
                
                # Record parsing metrics
                has_title = bool(text_result.get('title'))
                has_data = has_title or bool(text_result.get('brand')) or bool(text_result.get('price'))
                self.metrics.record_parsing_result('text', success=has_data, partial=has_title and not has_data)
            else:
                # Just get title for folder name without full parsing
                self._update_progress('Getting product name...', 15)
                try:
                    driver = self.browser_pool.get_driver()
                    title_elem = driver.find_element(By.CSS_SELECTOR, '#productTitle, #title, h1.a-size-large')
                    product_name = title_elem.text.strip() if title_elem else None
                except NoSuchElementException:
                    pass
                except Exception as e:
                    logger.debug(f"Error getting product name: {e}")
            
            # Fallback: try to get title from page one more time, then use ASIN only as last resort
            if not product_name or product_name == 'Unknown Product':
                try:
                    # Try alternative selectors for title
                    driver = self.browser_pool.get_driver()
                    alt_selectors = [
                        '#productTitle',
                        '#title',
                        'h1.a-size-large',
                        'h1[data-automation-id="title"]',
                        '.product-title',
                        'h1',
                    ]
                    for selector in alt_selectors:
                        try:
                            title_elem = driver.find_element(By.CSS_SELECTOR, selector)
                            product_name = title_elem.text.strip()
                            if product_name and len(product_name) > 5:  # Valid title
                                logger.info(f"Found product name using fallback selector: {selector}")
                                break
                        except:
                            continue
                    
                    # Only use ASIN if we still don't have a name
                    if not product_name or product_name == 'Unknown Product' or len(product_name) < 5:
                        try:
                            asin = url.split('/dp/')[-1].split('/')[0].split('?')[0]
                            if len(asin) == 10:
                                logger.warning(f"Using ASIN as product name: {asin}")
                                product_name = asin
                            else:
                                product_name = url.split('/')[-1].split('?')[0]
                        except:
                            product_name = 'Unknown Product'
                except:
                    product_name = 'Unknown Product'
            
            self.output_dir = create_output_structure(product_name)
            self.results['output_dir'] = self.output_dir
            
            # Update task with product name
            self.db.update_task(task_id, product_name=product_name)
            
            # Run selected agents
            current_progress = 25
            
            # Parse images based on individual checkboxes
            if any([
                config.get('images_hero', False),
                config.get('images_gallery', False),
                config.get('images_aplus_product', False),
                config.get('images_aplus_brand', False),
                config.get('images_aplus_manufacturer', False),
            ]):
                self._update_progress('Parsing images...', current_progress)
                try:
                    self._run_image_agents(config)
                except Exception as e:
                    logger.error(f"Image parsing failed: {e}")
                    self.results['errors'].append(f"Image parsing: {str(e)}")
                current_progress += 20
            
            # Parse reviews in parallel (Q&A is now part of text parsing)
            if config.get('reviews', False):
                self._update_progress('Parsing reviews...', current_progress)
                self._run_parallel_agents(config)
                current_progress += 20
            
            # Validate results (only if we have more than just images)
            has_other_data = config.get('reviews', False) or config.get('text', False)
            if has_other_data:
                self._update_progress('Validating data...', 85)
                self._run_validation(config)
            
            # Generate DOCX (generate even if only images are selected)
            has_images = any([
                config.get('images_hero', False),
                config.get('images_gallery', False),
                config.get('images_aplus_product', False),
                config.get('images_aplus_brand', False),
                config.get('images_aplus_manufacturer', False),
            ])
            images_data = self.results.get('images', {})
            has_any_images = images_data.get('total_images', 0) > 0 or \
                           len(images_data.get('hero', [])) > 0 or \
                           len(images_data.get('gallery', [])) > 0 or \
                           len(images_data.get('aplus_product', [])) > 0 or \
                           len(images_data.get('aplus_brand', [])) > 0 or \
                           len(images_data.get('aplus_manufacturer', [])) > 0
            has_text = self.results.get('text', {}).get('title')
            has_reviews = self.results.get('reviews', {}).get('summary') or self.results.get('reviews', {}).get('reviews')
            # Generate DOCX if we have text, images, or reviews
            if (has_images and has_any_images) or has_text or has_reviews:
                self._update_progress('Generating document...', 90 if has_other_data else 80)
                self._generate_docx()
            
            # Update task as completed
            self._update_progress('Completed!', 100)
            
            # Save metrics summary to results
            metrics_summary = self.metrics.get_summary()
            self.results['metrics'] = metrics_summary
            
            # Log metrics summary
            logger.info("=" * 80)
            logger.info("PARSING METRICS SUMMARY")
            logger.info("=" * 80)
            for category, stats in metrics_summary['parsing_metrics'].items():
                total = stats['success'] + stats['partial'] + stats['failed']
                if total > 0:
                    success_rate = (stats['success'] / total) * 100
                    logger.info(f"{category.upper()}: {stats['success']} success, {stats['partial']} partial, {stats['failed']} failed ({success_rate:.1f}% success rate)")
            
            if metrics_summary['fallback_usage']:
                logger.info(f"Fallback usage: {dict(metrics_summary['fallback_usage'])}")
            
            logger.info("=" * 80)
            
            self.db.update_task(
                task_id,
                status='completed',
                results=self._prepare_results_summary()
            )
            
            logger.info(f"Parsing completed for task #{task_id}")
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Parsing failed: {error_msg}\n{traceback.format_exc()}")
            self.results['errors'].append(error_msg)
            self.db.update_task(task_id, status='failed', error_message=error_msg)
            
        finally:
            # Close browser
            if self.browser_pool:
                self.browser_pool.close_driver()
        
        return self.results
    
    def _update_progress(self, message: str, percent: int):
        """Update progress via callback."""
        logger.info(f"Progress: {percent}% - {message}")
        if self.progress_callback:
            self.progress_callback(message, percent)
    
    def _save_dom_dump(self):
        """Save page source as DOM dump for atomic parsing."""
        try:
            driver = self.browser_pool.get_driver()
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            
            # Wait for main text content to load before saving DOM dump
            # This reduces fallback to Selenium
            logger.debug("Waiting for text content to load...")
            try:
                # In headless mode, use longer timeout for dynamic content
                wait_timeout = 10 if Settings.HEADLESS else 5
                wait = WebDriverWait(driver, wait_timeout)
                
                # Wait for at least one of the main text elements (including price blocks)
                wait.until(EC.any_of(
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#productTitle')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#productDescription_feature_div')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#detailBullets_feature_div')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#productDetails_detailBullets_sections1')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#important-information')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#corePriceDisplay_desktop_feature_div')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#corePrice_feature_div')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#apexPriceToPay')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, '.a-price')),
                    EC.presence_of_element_located((By.CSS_SELECTOR, '#climatePledgeFriendly')),
                ))
                logger.debug("Text content loaded, saving DOM dump...")
                
                # In headless mode, wait specifically for price to be visible with actual text
                if Settings.HEADLESS:
                    logger.debug("Waiting for price element with text in headless mode...")
                    try:
                        price_wait = WebDriverWait(driver, 5)  # Increased to 5 seconds for price in headless
                        # Wait for price element that has actual price text (not empty)
                        def price_has_text(driver):
                            price_selectors = [
                                '#corePriceDisplay_desktop_feature_div .a-price .a-offscreen',
                                '#corePrice_feature_div .a-price .a-offscreen',
                                '#apexPriceToPay .a-offscreen',
                                '.a-price .a-offscreen',
                                '#corePriceDisplay_desktop_feature_div',
                                '#corePrice_feature_div',
                                '#apexPriceToPay',
                            ]
                            for selector in price_selectors:
                                try:
                                    elements = driver.find_elements(By.CSS_SELECTOR, selector)
                                    for elem in elements:
                                        # Try multiple ways to get text
                                        text = elem.text or elem.get_attribute('textContent') or elem.get_attribute('innerText') or ''
                                        # Also check for aria-label which sometimes contains price
                                        aria_label = elem.get_attribute('aria-label') or ''
                                        combined_text = f"{text} {aria_label}"
                                        if combined_text and ('$' in combined_text or re.search(r'\d+\.\d+', combined_text)):
                                            logger.debug(f"Price found in headless mode via selector: {selector}, text: {combined_text[:50]}")
                                            return True
                                except Exception as e:
                                    logger.debug(f"Error checking price selector {selector}: {e}")
                                    continue
                            return False
                        
                        price_wait.until(price_has_text)
                        logger.info("✓ Price element with text found in headless mode")
                        # No delay needed - we're saving DOM dump immediately after this
                    except Exception as e:
                        logger.warning(f"Price wait timeout in headless mode (continuing anyway): {e}")
                
            except Exception as e:
                logger.debug(f"Text content wait timeout/error (continuing anyway): {e}")
            
            self.dom_dump = self.browser_pool.get_page_source()
            self.dom_soup = BeautifulSoup(self.dom_dump, 'html.parser')
            logger.info(f"DOM dump saved ({len(self.dom_dump)} chars)")
        except Exception as e:
            logger.warning(f"Failed to save DOM dump: {e}")
            self.dom_dump = None
            self.dom_soup = None
    
    def _log_performance(self, category: str, duration: float):
        """Log performance metrics for analysis."""
        if Settings.PERFORMANCE_LOGGING:
            self.performance_metrics[category] = duration
            logger.info(f"⏱️  {category}: {duration:.2f}s")
    
    def _run_with_retry(
        self, 
        func: Callable, 
        *args, 
        max_retries: int = None,
        **kwargs
    ) -> Dict:
        """
        Run function with retry logic.
        
        Args:
            func: Function to run
            max_retries: Maximum number of retries
            *args, **kwargs: Arguments to pass to function
            
        Returns:
            Function result or error dict
        """
        max_retries = max_retries or Settings.MAX_RETRIES
        last_error = None
        
        for attempt in range(max_retries):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                last_error = e
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed: {e}")
                
                if attempt < max_retries - 1:
                    # Exponential backoff
                    wait_time = (2 ** attempt) * Settings.RATE_LIMIT_MIN
                    time.sleep(wait_time)
        
        logger.error(f"All {max_retries} attempts failed")
        return {'errors': [str(last_error)]}
    
    def _run_image_agents(self, config: Dict):
        """Parse a single variant."""
        results = {}
        
        # Text
        text_agent = TextParserAgent(self.browser_pool, self.dom_soup)
        results['text'] = self._run_with_retry(text_agent.parse)
        
        # Images - use same logic as main parsing
        if any([
            config.get('images_hero', False),
            config.get('images_gallery', False),
            config.get('images_aplus_product', False),
            config.get('images_aplus_brand', False),
        ]):
            images_result = {
                'hero': [],
                'gallery': [],
                'aplus_product': [],
                'aplus_brand': [],
                'aplus_manufacturer': [],
                'total_images': 0,
                'errors': []
            }
            md5_cache = set()
            hero_url = None
            
            if config.get('images_hero', False):
                hero_parser = HeroParser(self.browser_pool, md5_cache)
                hero_images, hero_url = self._run_with_retry(hero_parser.parse, output_dir)
                images_result['hero'] = hero_images
            
            if config.get('images_gallery', False):
                gallery_parser = GalleryParser(self.browser_pool, md5_cache)
                gallery_images = self._run_with_retry(gallery_parser.parse, output_dir, hero_url)
                images_result['gallery'] = gallery_images
            
            if config.get('images_aplus_product', False):
                aplus_product_parser = APlusProductParser(self.browser_pool, md5_cache)
                aplus_product_images = self._run_with_retry(aplus_product_parser.parse, output_dir)
                images_result['aplus_product'] = aplus_product_images
            
            if config.get('images_aplus_brand', False):
                aplus_brand_parser = APlusBrandParser(self.browser_pool, md5_cache)
                aplus_brand_images = self._run_with_retry(aplus_brand_parser.parse, output_dir)
                images_result['aplus_brand'] = aplus_brand_images
            
            if config.get('images_aplus_manufacturer', False):
                aplus_manufacturer_parser = APlusManufacturerParser(self.browser_pool, md5_cache)
                aplus_manufacturer_images = self._run_with_retry(aplus_manufacturer_parser.parse, output_dir)
                images_result['aplus_manufacturer'] = aplus_manufacturer_images
            
            images_result['total_images'] = (
                len(images_result['hero']) +
                len(images_result['gallery']) +
                len(images_result['aplus_product']) +
                len(images_result['aplus_brand']) +
                len(images_result['aplus_manufacturer'])
            )
            results['images'] = images_result
        
        # Reviews
        if config.get('reviews', False):
            reviews_agent = ReviewsParserAgent(self.browser_pool)
            results['reviews'] = self._run_with_retry(
                reviews_agent.parse, 
                output_dir, 
                config.get('max_reviews', 10)
            )
        
        # Q&A is now parsed as part of text parsing (Product Description)
        
        return results
    
    def _run_image_agents(self, config: Dict):
        """Run image parsing agents based on config."""
        start_time = time.time()
        images_result = {
            'hero': [],
            'gallery': [],
            'aplus_product': [],
            'aplus_brand': [],
            'total_images': 0,
            'errors': []
        }
        
        # Shared MD5 cache for deduplication across all image parsers
        md5_cache = set()
        
        # Parse hero image (needed for gallery to exclude duplicates)
        hero_url = None
        if config.get('images_hero', False):
            try:
                agent_start = time.time()
                hero_parser = HeroParser(self.browser_pool, md5_cache)
                hero_images, hero_url = self._run_with_retry(hero_parser.parse, self.output_dir)
                images_result['hero'] = hero_images
                self._log_performance('Hero images', time.time() - agent_start)
                logger.info(f"Hero images: {len(hero_images)}")
            except Exception as e:
                logger.error(f"Hero parsing failed: {e}")
                images_result['errors'].append(f"Hero: {str(e)}")
        
        # Parse gallery images
        if config.get('images_gallery', False):
            try:
                agent_start = time.time()
                gallery_parser = GalleryParser(self.browser_pool, md5_cache)
                gallery_images = self._run_with_retry(gallery_parser.parse, self.output_dir, hero_url)
                images_result['gallery'] = gallery_images
                self._log_performance('Gallery images', time.time() - agent_start)
                logger.info(f"Gallery images: {len(gallery_images)}")
            except Exception as e:
                logger.error(f"Gallery parsing failed: {e}")
                images_result['errors'].append(f"Gallery: {str(e)}")
        
        # Parse A+ product images
        if config.get('images_aplus_product', False):
            try:
                agent_start = time.time()
                aplus_product_parser = APlusProductParser(self.browser_pool, md5_cache)
                aplus_product_result = self._run_with_retry(aplus_product_parser.parse, self.output_dir)
                # Handle both dict (new format) and list (old format) for compatibility
                if isinstance(aplus_product_result, dict):
                    images_result['aplus_product'] = aplus_product_result.get('images', [])
                    # Store alt texts in results
                    if 'image_alt_texts' not in self.results:
                        self.results['image_alt_texts'] = {}
                    self.results['image_alt_texts'].update(aplus_product_result.get('alt_texts', {}))
                else:
                    images_result['aplus_product'] = aplus_product_result
                self._log_performance('A+ Product images', time.time() - agent_start)
                logger.info(f"A+ product images: {len(images_result['aplus_product'])}")
            except Exception as e:
                logger.error(f"A+ product parsing failed: {e}")
                images_result['errors'].append(f"A+ Product: {str(e)}")
        
        # Parse A+ brand images
        if config.get('images_aplus_brand', False):
            try:
                agent_start = time.time()
                aplus_brand_parser = APlusBrandParser(self.browser_pool, md5_cache)
                aplus_brand_result = self._run_with_retry(aplus_brand_parser.parse, self.output_dir)
                # Handle both dict (new format) and list (old format) for compatibility
                if isinstance(aplus_brand_result, dict):
                    images_result['aplus_brand'] = aplus_brand_result.get('images', [])
                    # Store alt texts in results
                    if 'image_alt_texts' not in self.results:
                        self.results['image_alt_texts'] = {}
                    self.results['image_alt_texts'].update(aplus_brand_result.get('alt_texts', {}))
                else:
                    images_result['aplus_brand'] = aplus_brand_result
                self._log_performance('A+ Brand images', time.time() - agent_start)
                logger.info(f"A+ brand images: {len(images_result['aplus_brand'])}")
            except Exception as e:
                logger.error(f"A+ brand parsing failed: {e}")
                images_result['errors'].append(f"A+ Brand: {str(e)}")
        
        # Parse A+ manufacturer images
        if config.get('images_aplus_manufacturer', False):
            try:
                agent_start = time.time()
                aplus_manufacturer_parser = APlusManufacturerParser(self.browser_pool, md5_cache)
                aplus_manufacturer_result = self._run_with_retry(aplus_manufacturer_parser.parse, self.output_dir)
                # Handle both dict (new format) and list (old format) for compatibility
                if isinstance(aplus_manufacturer_result, dict):
                    images_result['aplus_manufacturer'] = aplus_manufacturer_result.get('images', [])
                    # Store alt texts in results
                    if 'image_alt_texts' not in self.results:
                        self.results['image_alt_texts'] = {}
                    self.results['image_alt_texts'].update(aplus_manufacturer_result.get('alt_texts', {}))
                else:
                    images_result['aplus_manufacturer'] = aplus_manufacturer_result
                self._log_performance('A+ Manufacturer images', time.time() - agent_start)
                logger.info(f"A+ manufacturer images: {len(images_result['aplus_manufacturer'])}")
            except Exception as e:
                logger.error(f"A+ manufacturer parsing failed: {e}")
                images_result['errors'].append(f"A+ Manufacturer: {str(e)}")
        
        # Calculate total
        images_result['total_images'] = (
            len(images_result['hero']) +
            len(images_result['gallery']) +
            len(images_result['aplus_product']) +
            len(images_result['aplus_brand']) +
            len(images_result['aplus_manufacturer'])
        )
        
        self.results['images'] = images_result
        self._log_performance('Total image parsing', time.time() - start_time)
    
    def _run_parallel_agents(self, config: Dict):
        """Run independent agents in parallel (reviews, qa)."""
        tasks = []
        
        # Prepare tasks
        if config.get('reviews', False):
            def run_reviews():
                agent = ReviewsParserAgent(self.browser_pool, self.dom_soup)
                max_reviews = 10
                return self._run_with_retry(agent.parse, self.output_dir, max_reviews)
            tasks.append(('reviews', run_reviews))
        
        # Q&A is now parsed as part of text parsing (Product Description)
        
        # Run tasks in parallel
        if len(tasks) == 1:
            # Single task - run directly (no need for thread pool)
            name, func = tasks[0]
            self.results[name] = func()
        elif len(tasks) > 1:
            # Multiple tasks - run in parallel
            with ThreadPoolExecutor(max_workers=len(tasks)) as executor:
                futures = {executor.submit(func): name for name, func in tasks}
                
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        self.results[name] = future.result()
                        logger.info(f"{name.capitalize()} parsing completed")
                    except Exception as e:
                        logger.error(f"{name.capitalize()} parsing failed: {e}")
                        self.results[name] = {'errors': [str(e)]}
    
    def _run_reviews_agent(self):
        """Run reviews parsing agent (legacy method, use _run_parallel_agents instead)."""
        agent = ReviewsParserAgent(self.browser_pool)
        max_reviews = 10  # Default, can be configured
        self.results['reviews'] = self._run_with_retry(
            agent.parse, 
            self.output_dir, 
            max_reviews
        )
    
    def _run_qa_agent(self):
        """Run Q&A parsing agent (legacy method - Q&A is now part of text parsing)."""
        # Q&A is now parsed as part of Product Description in text_parser
        pass
    
    def _run_validation(self, config: Dict = None):
        """Run validation agent."""
        agent = ValidatorAgent()
        self.results['validation'] = agent.validate(self.results, self.output_dir, config=config)
    
    def _generate_docx(self):
        """Generate DOCX document."""
        if not self.output_dir:
            return
        
        try:
            generator = DocxGenerator()
            
            # Get product name from text or from output directory name
            product_name = self.results.get('text', {}).get('title')
            if not product_name:
                # Try to get from output directory name
                output_path_obj = Path(self.output_dir)
                product_name = output_path_obj.name
                # Remove numerical suffix like (2), (3) if present
                product_name = re.sub(r'\s*\(\d+\)\s*$', '', product_name)
            
            if not product_name:
                product_name = 'Product'
            
            product_name = sanitize_filename(product_name)
            output_path = Path(self.output_dir) / f'{product_name}.docx'
            
            # Add output_dir to results for docx generator
            self.results['output_dir'] = self.output_dir
            
            generator.generate(self.results, str(output_path))
            self.results['docx_path'] = str(output_path)
            
            logger.info(f"DOCX generated: {output_path}")
            
        except Exception as e:
            logger.error(f"DOCX generation failed: {e}")
            self.results['errors'].append(f"DOCX generation failed: {str(e)}")
    
    def _prepare_results_summary(self) -> Dict:
        """Prepare summary for database storage."""
        # Calculate processing time
        start_time = self.results.get('start_time', time.time())
        processing_time = time.time() - start_time
        
        images_data = self.results.get('images', {})
        # Safely get counts - handle both list and None cases
        hero_list = images_data.get('hero') or []
        gallery_list = images_data.get('gallery') or []
        aplus_product_list = images_data.get('aplus_product') or []
        aplus_brand_list = images_data.get('aplus_brand') or []
        aplus_manufacturer_list = images_data.get('aplus_manufacturer') or []
        
        hero_count = len(hero_list) if isinstance(hero_list, list) else 0
        gallery_count = len(gallery_list) if isinstance(gallery_list, list) else 0
        aplus_product_count = len(aplus_product_list) if isinstance(aplus_product_list, list) else 0
        aplus_brand_count = len(aplus_brand_list) if isinstance(aplus_brand_list, list) else 0
        aplus_manufacturer_count = len(aplus_manufacturer_list) if isinstance(aplus_manufacturer_list, list) else 0
        
        summary = {
            'product_name': self.results.get('text', {}).get('title'),
            'asin': self.results.get('text', {}).get('asin'),
            'output_dir': self.output_dir,
            'images': {
                'hero': hero_count,
                'gallery': gallery_count,
                'aplus_product': aplus_product_count,
                'aplus_brand': aplus_brand_count,
                'aplus_manufacturer': aplus_manufacturer_count,
                'aplus': aplus_product_count + aplus_brand_count + aplus_manufacturer_count,
            },
            'reviews_count': len(self.results.get('reviews', {}).get('reviews', [])),
            'qa_count': self.results.get('text', {}).get('qa_count', 0),  # Q&A is now part of text parsing
            'validation_score': self.results.get('validation', {}).get('completeness_score', 0),
            'processing_time_seconds': round(processing_time, 2),
            'processing_time_formatted': self._format_processing_time(processing_time),
            'performance_metrics': self.performance_metrics if Settings.PERFORMANCE_LOGGING else {},
            'errors': self.results.get('errors', [])
        }
        
        return summary
    
    def _format_processing_time(self, seconds: float) -> str:
        """Format processing time in human-readable format."""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}m {secs}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

