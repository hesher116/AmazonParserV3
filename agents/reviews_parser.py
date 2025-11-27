"""Reviews Parser Agent - Parses customer reviews and statistics"""
import re
from typing import Dict, List, Optional
from pathlib import Path

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from core.browser_pool import BrowserPool
from utils.text_utils import clean_html_tags, filter_ad_phrases, parse_rating
from utils.file_utils import save_image_with_dedup, get_high_res_url, is_excluded_url
from utils.logger import get_logger

logger = get_logger(__name__)


class ReviewsParserAgent:
    """Agent for parsing customer reviews from Amazon product page."""
    
    def __init__(self, browser_pool: BrowserPool):
        self.browser = browser_pool
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
        driver = self.browser.get_driver()
        
        summary = {
            'rating': None,
            'rating_count': None,
            'star_distribution': {},
            'customers_say': None,
            'key_aspects': []
        }
        
        # Overall rating
        try:
            rating_element = driver.find_element(
                By.CSS_SELECTOR, 
                '#acrPopover, .a-icon-star span, [data-hook="rating-out-of-text"]'
            )
            rating_text = rating_element.get_attribute('title') or rating_element.text
            parsed = parse_rating(rating_text)
            summary['rating'] = parsed.get('rating')
        except NoSuchElementException:
            pass
        
        # Rating count
        try:
            count_element = driver.find_element(
                By.CSS_SELECTOR,
                '#acrCustomerReviewText, [data-hook="total-review-count"]'
            )
            count_text = count_element.text
            match = re.search(r'([\d,]+)', count_text)
            if match:
                summary['rating_count'] = match.group(1).replace(',', '')
        except NoSuchElementException:
            pass
        
        # Star distribution (histogram)
        try:
            histogram = driver.find_element(By.CSS_SELECTOR, '#histogramTable, .cr-widget-Histogram')
            rows = histogram.find_elements(By.CSS_SELECTOR, 'tr, .a-histogram-row')
            
            for row in rows:
                try:
                    star_text = row.find_element(
                        By.CSS_SELECTOR, 
                        '.a-text-right a, .a-link-normal'
                    ).text
                    percent_text = row.find_element(
                        By.CSS_SELECTOR, 
                        '.a-text-right + td, .a-size-small'
                    ).text
                    
                    star_match = re.search(r'(\d)', star_text)
                    percent_match = re.search(r'(\d+)%', percent_text)
                    
                    if star_match and percent_match:
                        stars = star_match.group(1)
                        percent = percent_match.group(1)
                        summary['star_distribution'][f'{stars}_star'] = f'{percent}%'
                except NoSuchElementException:
                    continue
                    
        except NoSuchElementException:
            pass
        
        # "Customers say" summary
        try:
            say_element = driver.find_element(
                By.CSS_SELECTOR,
                '[data-hook="cr-summarization-attribute"]'
            )
            summary['customers_say'] = clean_html_tags(say_element.text)
        except NoSuchElementException:
            pass
        
        # Key aspects (Softness, Scent, etc.)
        try:
            aspects = driver.find_elements(
                By.CSS_SELECTOR,
                '.cr-lighthouse-term, [data-hook="cr-lighthouse-term"]'
            )
            for aspect in aspects:
                text = clean_html_tags(aspect.text)
                if text:
                    summary['key_aspects'].append(text)
        except NoSuchElementException:
            pass
        
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
        driver = self.browser.get_driver()
        reviews = []
        
        # Scroll to reviews section
        try:
            reviews_section = driver.find_element(
                By.CSS_SELECTOR, 
                '#cm-cr-dp-review-list, #customerReviews'
            )
            self.browser.scroll_to_element(reviews_section)
        except NoSuchElementException:
            logger.warning("Reviews section not found")
            return reviews
        
        # Find individual reviews
        review_elements = driver.find_elements(
            By.CSS_SELECTOR,
            '[data-hook="review"], .review, .a-section.review'
        )
        
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
        
        # Reviewer name
        try:
            name_el = element.find_element(
                By.CSS_SELECTOR, 
                '.a-profile-name, [data-hook="genome-widget"]'
            )
            review['reviewer_name'] = clean_html_tags(name_el.text)
        except NoSuchElementException:
            pass
        
        # Rating
        try:
            rating_el = element.find_element(
                By.CSS_SELECTOR, 
                '[data-hook="review-star-rating"] span, .a-icon-star span'
            )
            rating_text = rating_el.get_attribute('textContent') or rating_el.text
            parsed = parse_rating(rating_text)
            review['rating'] = parsed.get('rating')
        except NoSuchElementException:
            pass
        
        # Title
        try:
            title_el = element.find_element(
                By.CSS_SELECTOR, 
                '[data-hook="review-title"] span, .review-title'
            )
            review['title'] = clean_html_tags(title_el.text)
        except NoSuchElementException:
            pass
        
        # Review text
        try:
            text_el = element.find_element(
                By.CSS_SELECTOR, 
                '[data-hook="review-body"] span, .review-text'
            )
            review['text'] = filter_ad_phrases(clean_html_tags(text_el.text))
        except NoSuchElementException:
            pass
        
        # Date
        try:
            date_el = element.find_element(
                By.CSS_SELECTOR, 
                '[data-hook="review-date"], .review-date'
            )
            review['date'] = clean_html_tags(date_el.text)
        except NoSuchElementException:
            pass
        
        # Variant (Color, Size, etc.)
        try:
            variant_el = element.find_element(
                By.CSS_SELECTOR, 
                '[data-hook="format-strip"], .a-size-mini.a-color-secondary'
            )
            review['variant'] = clean_html_tags(variant_el.text)
        except NoSuchElementException:
            pass
        
        # Verified Purchase
        try:
            element.find_element(
                By.CSS_SELECTOR, 
                '[data-hook="avp-badge"], .a-color-state'
            )
            review['verified_purchase'] = True
        except NoSuchElementException:
            pass
        
        # Helpful count
        try:
            helpful_el = element.find_element(
                By.CSS_SELECTOR, 
                '[data-hook="helpful-vote-statement"], .a-size-small.a-color-tertiary'
            )
            helpful_text = helpful_el.text
            match = re.search(r'(\d+)', helpful_text)
            if match:
                review['helpful_count'] = match.group(1)
        except NoSuchElementException:
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
            self.browser._random_sleep(0.5, 1.0)
            
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

