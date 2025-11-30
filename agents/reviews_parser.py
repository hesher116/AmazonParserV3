"""Reviews Parser Agent - Parses customer reviews and statistics"""
import re
from typing import Dict, List, Optional
from pathlib import Path

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from agents.base_parser import BaseParser
from core.browser_pool import BrowserPool
from utils.text_utils import clean_html_tags, filter_ad_phrases, parse_rating
from utils.file_utils import save_image_with_dedup, get_high_res_url, is_excluded_url
from utils.logger import get_logger

logger = get_logger(__name__)


class ReviewsParserAgent(BaseParser):
    """Agent for parsing customer reviews from Amazon product page."""
    
    def __init__(self, browser_pool: BrowserPool, dom_soup: Optional[BeautifulSoup] = None):
        super().__init__(browser_pool, dom_soup)
        self.md5_cache = set()
    
    def parse(self, output_dir: str, max_reviews: int = 10) -> Dict:
        """
        Parse reviews from the current page.
        
        Args:
            output_dir: Directory to save review images
            max_reviews: Maximum number of detailed reviews to parse
            
        Returns:
            Dictionary with review data
        """
        logger.info("Starting reviews parsing...")
        
        results = {
            'summary': {},
            'reviews': [],
            'review_images': [],
            'errors': []
        }
        
        try:
            # Parse summary statistics
            results['summary'] = self.parse_reviews_summary()
            
            # Parse detailed reviews
            results['reviews'] = self.parse_review_details(max_reviews)
            
            # Parse review images carousel
            results['review_images'] = self.parse_review_images(output_dir)
            
            logger.info(
                f"Reviews parsing complete: {len(results['reviews'])} reviews, "
                f"{len(results['review_images'])} images"
            )
            
        except Exception as e:
            logger.error(f"Reviews parsing error: {e}")
            results['errors'].append(str(e))
        
        return results
    
    def parse_reviews_summary(self) -> Dict:
        """
        Parse review summary statistics.
        
        Returns:
            Dictionary with summary data
        """
        summary = {
            'rating': None,
            'rating_count': None,
            'star_distribution': {},
            'customers_say': None,
            'key_aspects': [],
            'top_reviews_heading': None  # "Top reviews from the United States"
        }
        
        # Overall rating
        rating_element = self.find_element_by_selector(
            '#acrPopover, .a-icon-star span, [data-hook="rating-out-of-text"]',
            use_dom=True
        )
        if rating_element:
            rating_text = self.get_attribute_from_element(rating_element, 'title') or \
                         self.get_text_from_element(rating_element)
            parsed = parse_rating(rating_text)
            summary['rating'] = parsed.get('rating')
        
        # Rating count
        count_element = self.find_element_by_selector(
            '#acrCustomerReviewText, [data-hook="total-review-count"]',
            use_dom=True
        )
        if count_element:
            count_text = self.get_text_from_element(count_element)
            match = re.search(r'([\d,]+)', count_text)
            if match:
                summary['rating_count'] = match.group(1).replace(',', '')
        
        # Star distribution (histogram)
        histogram = self.find_element_by_selector(
            '#histogramTable, .cr-widget-Histogram',
            use_dom=True
        )
        if histogram:
            rows = self.find_elements_by_selector('tr, .a-histogram-row', use_dom=True)
            
            for row in rows:
                star_elem = None
                percent_elem = None
                
                # Try to find star and percent in row
                if hasattr(row, 'select_one'):  # BeautifulSoup
                    star_elem = row.select_one('.a-text-right a, .a-link-normal')
                    percent_elem = row.select_one('.a-text-right + td, .a-size-small')
                elif hasattr(row, 'find_element'):  # Selenium
                    try:
                        star_elem = row.find_element(By.CSS_SELECTOR, '.a-text-right a, .a-link-normal')
                        percent_elem = row.find_element(By.CSS_SELECTOR, '.a-text-right + td, .a-size-small')
                    except:
                        continue
                
                if star_elem and percent_elem:
                    star_text = self.get_text_from_element(star_elem)
                    percent_text = self.get_text_from_element(percent_elem)
                    
                    star_match = re.search(r'(\d)', star_text)
                    percent_match = re.search(r'(\d+)%', percent_text)
                    
                    if star_match and percent_match:
                        stars = star_match.group(1)
                        percent = percent_match.group(1)
                        summary['star_distribution'][f'{stars}_star'] = f'{percent}%'
        
        # "Customers say" summary - find in #product-summary with proper structure
        customers_say_container = self.find_element_by_selector('#product-summary, [data-hook="cr-insights-widget-summary"]', use_dom=True)
        if customers_say_container:
            # Check if heading exists
            if hasattr(customers_say_container, 'select_one'):  # BeautifulSoup
                heading = customers_say_container.select_one('h3[data-hook="cr-insights-heading-label"], h3')
                if heading:
                    heading_text = heading.get_text(strip=True)
                    if 'customers say' in heading_text.lower():
                        # Find the paragraph with text
                        text_para = customers_say_container.select_one('p.a-spacing-small span, p.a-spacing-small')
                        if text_para:
                            say_text = clean_html_tags(text_para.get_text(strip=True))
                            if say_text and len(say_text) > 20:
                                summary['customers_say'] = say_text
                                logger.debug(f"Found 'Customers say': {say_text[:100]}...")
            else:  # Selenium
                try:
                    driver = self.browser.get_driver()
                    heading = customers_say_container.find_element(By.CSS_SELECTOR, 'h3[data-hook="cr-insights-heading-label"], h3')
                    heading_text = heading.text.strip()
                    if 'customers say' in heading_text.lower():
                        text_para = customers_say_container.find_element(By.CSS_SELECTOR, 'p.a-spacing-small span, p.a-spacing-small')
                        say_text = clean_html_tags(text_para.text.strip())
                        if say_text and len(say_text) > 20:
                            summary['customers_say'] = say_text
                            logger.debug(f"Found 'Customers say': {say_text[:100]}...")
                except Exception as e:
                    logger.debug(f"Error parsing 'Customers say': {e}")
        
        # "Top reviews from the United States" heading - use data-hook="dp-local-reviews-header"
        try:
            # Try specific selector first
            heading = self.find_element_by_selector(
                'h3[data-hook="dp-local-reviews-header"]',
                use_dom=True
            )
            if heading:
                heading_text = clean_html_tags(self.get_text_from_element(heading))
                if heading_text:
                    summary['top_reviews_heading'] = heading_text
                    logger.debug(f"Found 'Top reviews' heading: {heading_text}")
            else:
                # Fallback: search all h3 headings
                if self.dom_soup:
                    headings = self.dom_soup.select('h3, h2')
                    for heading in headings:
                        heading_text = heading.get_text(strip=True)
                        if 'top reviews' in heading_text.lower() and 'united states' in heading_text.lower():
                            summary['top_reviews_heading'] = heading_text
                            logger.debug(f"Found 'Top reviews' heading: {heading_text}")
                            break
                else:  # Selenium
                    driver = self.browser.get_driver()
                    headings = driver.find_elements(By.CSS_SELECTOR, 'h3, h2')
                    for heading in headings:
                        heading_text = heading.text.strip()
                        if 'top reviews' in heading_text.lower() and 'united states' in heading_text.lower():
                            summary['top_reviews_heading'] = heading_text
                            logger.debug(f"Found 'Top reviews' heading: {heading_text}")
                            break
        except Exception as e:
            logger.debug(f"Error checking for top reviews heading: {e}")
        
        # Key aspects (Softness, Scent, etc.)
        aspects = self.find_elements_by_selector(
            '.cr-lighthouse-term, [data-hook="cr-lighthouse-term"]',
            use_dom=True
        )
        for aspect in aspects:
            text = clean_html_tags(self.get_text_from_element(aspect))
            if text:
                summary['key_aspects'].append(text)
        
        logger.debug(f"Review summary: rating={summary['rating']}, count={summary['rating_count']}")
        return summary
    
    def parse_review_details(self, max_reviews: int = 10) -> List[Dict]:
        """
        Parse detailed reviews.
        
        Args:
            max_reviews: Maximum number of reviews to parse
            
        Returns:
            List of review dictionaries
        """
        reviews = []
        
        # Try to find reviews from DOM first (faster, no scroll needed)
        review_elements = self.find_elements_by_selector(
            '[data-hook="review"], .review, .a-section.review',
            use_dom=True
        )
        
        # If not found in DOM, try Selenium (may need scroll for lazy-loaded reviews)
        if not review_elements:
            driver = self.browser.get_driver()
            try:
                reviews_section = driver.find_element(
                    By.CSS_SELECTOR, 
                    '#cm-cr-dp-review-list, #customerReviews'
                )
                self.browser.scroll_to_element(reviews_section)
                review_elements = driver.find_elements(
                    By.CSS_SELECTOR,
                    '[data-hook="review"], .review, .a-section.review'
                )
            except NoSuchElementException:
                logger.warning("Reviews section not found")
                return reviews
        
        logger.info(f"Found {len(review_elements)} reviews on page")
        
        for i, review_el in enumerate(review_elements[:max_reviews]):
            try:
                # Skip sponsored reviews
                if self._is_sponsored_review(review_el):
                    logger.debug(f"Skipping sponsored review {i}")
                    continue
                
                review = self._parse_single_review(review_el)
                if review:
                    reviews.append(review)
                    
            except Exception as e:
                logger.debug(f"Failed to parse review {i}: {e}")
        
        return reviews
    
    def _parse_single_review(self, element) -> Optional[Dict]:
        """Parse a single review element."""
        review = {
            'reviewer_name': None,
            'rating': None,
            'title': None,
            'text': None,
            'date': None,
            'variant': None,
            'verified_purchase': False,
            'helpful_count': None
        }
        
        # Check if element is BeautifulSoup or Selenium
        is_soup = hasattr(element, 'select_one')
        
        # Reviewer name
        try:
            if is_soup:
                name_el = element.select_one('.a-profile-name, [data-hook="genome-widget"] .a-profile-name')
            else:
                name_el = element.find_element(By.CSS_SELECTOR, '.a-profile-name, [data-hook="genome-widget"] .a-profile-name')
            if name_el:
                review['reviewer_name'] = clean_html_tags(self.get_text_from_element(name_el))
        except (NoSuchElementException, AttributeError):
            pass
        
        # Rating
        try:
            if is_soup:
                rating_el = element.select_one('[data-hook="review-star-rating"] span, .a-icon-star span, [data-hook="review-star-rating"]')
            else:
                rating_el = element.find_element(By.CSS_SELECTOR, '[data-hook="review-star-rating"] span, .a-icon-star span')
            if rating_el:
                rating_text = self.get_text_from_element(rating_el)
                parsed = parse_rating(rating_text)
                review['rating'] = parsed.get('rating')
        except (NoSuchElementException, AttributeError):
            pass
        
        # Title
        try:
            if is_soup:
                title_el = element.select_one('[data-hook="review-title"] span, [data-hook="review-title"], .review-title')
            else:
                title_el = element.find_element(By.CSS_SELECTOR, '[data-hook="review-title"] span, .review-title')
            if title_el:
                review['title'] = clean_html_tags(self.get_text_from_element(title_el))
        except (NoSuchElementException, AttributeError):
            pass
        
        # Review text
        try:
            if is_soup:
                text_el = element.select_one('[data-hook="review-body"] span, [data-hook="review-body"], .review-text')
            else:
                text_el = element.find_element(By.CSS_SELECTOR, '[data-hook="review-body"] span, .review-text')
            if text_el:
                review['text'] = filter_ad_phrases(clean_html_tags(self.get_text_from_element(text_el)))
        except (NoSuchElementException, AttributeError):
            pass
        
        # Date
        try:
            if is_soup:
                date_el = element.select_one('[data-hook="review-date"], .review-date')
            else:
                date_el = element.find_element(By.CSS_SELECTOR, '[data-hook="review-date"], .review-date')
            if date_el:
                review['date'] = clean_html_tags(self.get_text_from_element(date_el))
        except (NoSuchElementException, AttributeError):
            pass
        
        # Variant (Color, Size, etc.) - removed, no longer needed
        
        # Verified Purchase
        try:
            if is_soup:
                verified_el = element.select_one('[data-hook="avp-badge"], .a-color-state')
            else:
                verified_el = element.find_element(By.CSS_SELECTOR, '[data-hook="avp-badge"], .a-color-state')
            if verified_el:
                review['verified_purchase'] = True
        except (NoSuchElementException, AttributeError):
            pass
        
        # Helpful count
        try:
            if is_soup:
                helpful_el = element.select_one('[data-hook="helpful-vote-statement"], .a-size-small.a-color-tertiary')
            else:
                helpful_el = element.find_element(By.CSS_SELECTOR, '[data-hook="helpful-vote-statement"], .a-size-small.a-color-tertiary')
            if helpful_el:
                helpful_text = self.get_text_from_element(helpful_el)
                match = re.search(r'(\d+)', helpful_text)
                if match:
                    review['helpful_count'] = match.group(1)
        except (NoSuchElementException, AttributeError):
            pass
        
        # Only return if we have at least rating or text
        if review['rating'] or review['text']:
            return review
        return None
    
    def _is_sponsored_review(self, element) -> bool:
        """Check if review is sponsored."""
        try:
            html = element.get_attribute('outerHTML').lower()
            return 'sponsored' in html or 'advertisement' in html
        except Exception:
            return False
    
    def parse_review_images(self, output_dir: str) -> List[str]:
        """
        Parse images from "Reviews with images" carousel.
        
        Args:
            output_dir: Directory to save images
            
        Returns:
            List of saved image paths
        """
        saved_images = []
        images_dir = Path(output_dir) / 'QAImages'
        
        driver = self.browser.get_driver()
        
        try:
            # Find review images carousel
            carousel = driver.find_element(
                By.CSS_SELECTOR,
                '#cm-cr-dp-review-images-carousel, [data-hook="cr-media-gallery-images"]'
            )
            
            self.browser.scroll_to_element(carousel)
            # No delay needed - scroll_to_element now waits for element visibility
            
            # Find all images in carousel
            images = carousel.find_elements(By.TAG_NAME, 'img')
            
            # Create folder only if we have images
            if images:
                images_dir.mkdir(parents=True, exist_ok=True)
            
            for i, img in enumerate(images):
                try:
                    url = img.get_attribute('src')
                    if url and not is_excluded_url(url):
                        url = get_high_res_url(url)
                        output_path = images_dir / f'review{i + 1}.jpg'
                        if save_image_with_dedup(url, str(output_path), self.md5_cache):
                            saved_images.append(str(output_path))
                except Exception as e:
                    logger.debug(f"Failed to save review image {i}: {e}")
                    
        except NoSuchElementException:
            logger.debug("No review images carousel found")
        
        return saved_images

