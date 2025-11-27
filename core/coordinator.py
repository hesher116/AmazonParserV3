"""Coordinator - Manages agent execution and results collection"""
import re
import time
import traceback
from typing import Dict, List, Optional, Callable
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from core.browser_pool import BrowserPool
from core.database import Database
from core.docx_generator import DocxGenerator
from agents.image_parser import ImageParserAgent
from agents.text_parser import TextParserAgent
from agents.reviews_parser import ReviewsParserAgent
from agents.qa_parser import QAParserAgent
from agents.variant_detector import VariantDetectorAgent
from agents.validator import ValidatorAgent
from utils.file_utils import create_output_structure, create_variant_structure, sanitize_filename
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
            'variants': {},
            'validation': {},
            'errors': [],
            'output_dir': None
        }
        
        try:
            # Update task status
            self.db.update_task(task_id, status='running')
            self._update_progress('Initializing browser...', 5)
            
            # Initialize browser
            self.browser_pool = BrowserPool()
            
            # Navigate to product page
            self._update_progress('Loading product page...', 10)
            if not self.browser_pool.navigate_to(url):
                raise Exception("Failed to load product page")
            
            # Get product name for folder (always needed, but parse full text only if checkbox is checked)
            product_name = None
            if config.get('text', False):
                # Full text parsing
                self._update_progress('Parsing product info...', 15)
                text_agent = TextParserAgent(self.browser_pool)
                self.results['text'] = self._run_with_retry(text_agent.parse)
                product_name = self.results['text'].get('title', 'Unknown Product')
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
            
            # Check for variants if enabled
            if config.get('variants', False):
                self._update_progress('Detecting variants...', 20)
                self._handle_variants(config)
            
            # Run selected agents
            current_progress = 25
            
            if config.get('images', False):
                self._update_progress('Parsing images...', current_progress)
                try:
                    self._run_image_agent()
                except Exception as e:
                    logger.error(f"Image parsing failed: {e}")
                    self.results['errors'].append(f"Image parsing: {str(e)}")
                current_progress += 20
            
            if config.get('reviews', False):
                self._update_progress('Parsing reviews...', current_progress)
                self._run_reviews_agent()
                current_progress += 20
            
            if config.get('qa', False):
                self._update_progress('Parsing Q&A...', current_progress)
                self._run_qa_agent()
                current_progress += 15
            
            # Validate results (only if we have more than just images)
            has_other_data = config.get('reviews', False) or config.get('qa', False)
            if has_other_data:
                self._update_progress('Validating data...', 85)
                self._run_validation()
            
            # Generate DOCX (generate even if only images are selected)
            has_images = config.get('images', False) and self.results.get('images', {}).get('total_images', 0) > 0
            has_text = self.results.get('text', {}).get('title')
            if has_images or has_text:
                self._update_progress('Generating document...', 90 if has_other_data else 80)
                self._generate_docx()
            
            # Update task as completed
            self._update_progress('Completed!', 100)
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
    
    def _handle_variants(self, config: Dict):
        """Handle variant detection and parsing."""
        variant_agent = VariantDetectorAgent(self.browser_pool)
        variant_result = self._run_with_retry(variant_agent.parse)
        self.results['variants'] = variant_result
        
        if variant_result.get('has_variants') and variant_result.get('variants'):
            variants = variant_result['variants']
            logger.info(f"Found {len(variants)} variants, parsing each...")
            
            # Store main product results
            main_results = dict(self.results)
            
            # Parse each variant
            for i, variant in enumerate(variants):
                if not variant.get('available', True):
                    logger.debug(f"Skipping unavailable variant: {variant.get('name')}")
                    continue
                
                if variant.get('selected'):
                    # This is the current variant, already parsed
                    continue
                
                self._update_progress(
                    f"Parsing variant: {variant.get('name', 'Unknown')}...",
                    25 + (i * 5) % 20
                )
                
                try:
                    # Navigate to variant
                    if variant_agent.click_variant(variant):
                        variant_name = variant.get('name', f'variant_{i}')
                        variant_dir = create_variant_structure(self.output_dir, variant_name)
                        
                        # Parse this variant
                        variant_results = self._parse_variant(variant_dir, config)
                        
                        # Store variant results
                        if 'variant_results' not in self.results:
                            self.results['variant_results'] = []
                        
                        self.results['variant_results'].append({
                            'name': variant_name,
                            'asin': variant.get('asin'),
                            'output_dir': variant_dir,
                            'results': variant_results
                        })
                        
                except Exception as e:
                    logger.error(f"Failed to parse variant {variant.get('name')}: {e}")
    
    def _parse_variant(self, output_dir: str, config: Dict) -> Dict:
        """Parse a single variant."""
        results = {}
        
        # Text
        text_agent = TextParserAgent(self.browser_pool)
        results['text'] = self._run_with_retry(text_agent.parse)
        
        # Images
        if config.get('images', False):
            image_agent = ImageParserAgent(self.browser_pool)
            results['images'] = self._run_with_retry(image_agent.parse, output_dir)
        
        # Reviews
        if config.get('reviews', False):
            reviews_agent = ReviewsParserAgent(self.browser_pool)
            results['reviews'] = self._run_with_retry(
                reviews_agent.parse, 
                output_dir, 
                config.get('max_reviews', 10)
            )
        
        # Q&A
        if config.get('qa', False):
            qa_agent = QAParserAgent(self.browser_pool)
            results['qa'] = self._run_with_retry(qa_agent.parse)
        
        return results
    
    def _run_image_agent(self):
        """Run image parsing agent."""
        agent = ImageParserAgent(self.browser_pool)
        self.results['images'] = self._run_with_retry(agent.parse, self.output_dir)
    
    def _run_reviews_agent(self):
        """Run reviews parsing agent."""
        agent = ReviewsParserAgent(self.browser_pool)
        max_reviews = 10  # Default, can be configured
        self.results['reviews'] = self._run_with_retry(
            agent.parse, 
            self.output_dir, 
            max_reviews
        )
    
    def _run_qa_agent(self):
        """Run Q&A parsing agent."""
        agent = QAParserAgent(self.browser_pool)
        self.results['qa'] = self._run_with_retry(agent.parse)
    
    def _run_validation(self):
        """Run validation agent."""
        agent = ValidatorAgent()
        self.results['validation'] = agent.validate(self.results, self.output_dir)
    
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
            
            generator.generate(self.results, str(output_path))
            self.results['docx_path'] = str(output_path)
            
            logger.info(f"DOCX generated: {output_path}")
            
        except Exception as e:
            logger.error(f"DOCX generation failed: {e}")
            self.results['errors'].append(f"DOCX generation failed: {str(e)}")
    
    def _prepare_results_summary(self) -> Dict:
        """Prepare summary for database storage."""
        summary = {
            'product_name': self.results.get('text', {}).get('title'),
            'asin': self.results.get('text', {}).get('asin'),
            'output_dir': self.output_dir,
            'images': {
                'hero': len(self.results.get('images', {}).get('hero', [])),
                'gallery': len(self.results.get('images', {}).get('gallery', [])),
                'aplus': len(self.results.get('images', {}).get('aplus_brand', [])) + 
                         len(self.results.get('images', {}).get('aplus_product', [])),
            },
            'reviews_count': len(self.results.get('reviews', {}).get('reviews', [])),
            'qa_count': len(self.results.get('qa', {}).get('qa_pairs', [])),
            'variants_count': len(self.results.get('variants', {}).get('variants', [])),
            'validation_score': self.results.get('validation', {}).get('completeness_score', 0),
            'errors': self.results.get('errors', [])
        }
        
        return summary

