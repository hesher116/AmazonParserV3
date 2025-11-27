"""Q&A Parser Agent - Parses questions and answers"""
from typing import Dict, List

from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from core.browser_pool import BrowserPool
from utils.text_utils import clean_html_tags, filter_ad_phrases
from utils.logger import get_logger

logger = get_logger(__name__)


class QAParserAgent:
    """Agent for parsing Q&A from Amazon product page."""
    
    def __init__(self, browser_pool: BrowserPool):
        self.browser = browser_pool
    
    def parse(self, max_qa: int = 20) -> Dict:
        """
        Parse Q&A from the current page.
        
        Args:
            max_qa: Maximum number of Q&A pairs to parse
            
        Returns:
            Dictionary with Q&A data
        """
        logger.info("Starting Q&A parsing...")
        
        results = {
            'total_questions': None,
            'qa_pairs': [],
            'errors': []
        }
        
        try:
            # Get total questions count
            results['total_questions'] = self._get_total_questions()
            
            # Parse Q&A pairs
            results['qa_pairs'] = self._parse_qa_pairs(max_qa)
            
            logger.info(f"Q&A parsing complete: {len(results['qa_pairs'])} pairs")
            
        except Exception as e:
            logger.error(f"Q&A parsing error: {e}")
            results['errors'].append(str(e))
        
        return results
    
    def _get_total_questions(self) -> str:
        """Get total number of questions."""
        driver = self.browser.get_driver()
        
        selectors = [
            '#askATFLink',
            '[data-hook="qa-questions-count"]',
            '.a-section.askInlineWidget a',
        ]
        
        for selector in selectors:
            try:
                element = driver.find_element(By.CSS_SELECTOR, selector)
                text = clean_html_tags(element.text)
                if text:
                    return text
            except NoSuchElementException:
                continue
        
        return None
    
    def _parse_qa_pairs(self, max_qa: int) -> List[Dict]:
        """
        Parse Q&A pairs from the page.
        
        Args:
            max_qa: Maximum pairs to parse
            
        Returns:
            List of Q&A dictionaries
        """
        driver = self.browser.get_driver()
        qa_pairs = []
        
        # Scroll to Q&A section
        try:
            qa_section = driver.find_element(
                By.CSS_SELECTOR,
                '#ask-btf_feature_div, #qa-content, .askWidgetQuestions'
            )
            self.browser.scroll_to_element(qa_section)
            self.browser._random_sleep(0.5, 1.0)
        except NoSuchElementException:
            logger.debug("Q&A section not found")
            return qa_pairs
        
        # Find Q&A items
        qa_selectors = [
            '.a-section.askTeaserQuestions > div',
            '[data-hook="ask-content"] .a-section',
            '.askInlineWidget .a-fixed-left-grid',
        ]
        
        for selector in qa_selectors:
            try:
                qa_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                
                if qa_elements:
                    for element in qa_elements[:max_qa]:
                        qa_pair = self._parse_single_qa(element)
                        if qa_pair:
                            qa_pairs.append(qa_pair)
                    break
                    
            except NoSuchElementException:
                continue
        
        # Alternative parsing for different layout
        if not qa_pairs:
            qa_pairs = self._parse_qa_alternative(max_qa)
        
        return qa_pairs
    
    def _parse_single_qa(self, element) -> Dict:
        """Parse a single Q&A element."""
        qa = {
            'question': None,
            'answer': None,
            'votes': None,
            'answer_by': None,
            'answer_date': None
        }
        
        # Question
        question_selectors = [
            '.a-text-bold, .askTeaserQuestion',
            'a[href*="ask/questions"]',
            '.a-link-normal span',
        ]
        
        for selector in question_selectors:
            try:
                q_el = element.find_element(By.CSS_SELECTOR, selector)
                text = clean_html_tags(q_el.text)
                if text and '?' in text or text.startswith('Q:'):
                    qa['question'] = text.replace('Q:', '').strip()
                    break
            except NoSuchElementException:
                continue
        
        # Answer
        answer_selectors = [
            '.askLongText, .askTeaserAnswer',
            '.a-size-base:not(.a-text-bold)',
        ]
        
        for selector in answer_selectors:
            try:
                a_el = element.find_element(By.CSS_SELECTOR, selector)
                text = clean_html_tags(a_el.text)
                text = filter_ad_phrases(text)
                if text and len(text) > 10:
                    qa['answer'] = text.replace('A:', '').strip()
                    break
            except NoSuchElementException:
                continue
        
        # Votes
        try:
            votes_el = element.find_element(By.CSS_SELECTOR, '.askVoteCount')
            qa['votes'] = clean_html_tags(votes_el.text)
        except NoSuchElementException:
            pass
        
        # Answer by / Date
        try:
            info_el = element.find_element(
                By.CSS_SELECTOR, 
                '.a-color-tertiary, .a-size-small.a-color-secondary'
            )
            info_text = clean_html_tags(info_el.text)
            if 'by' in info_text.lower():
                qa['answer_by'] = info_text
        except NoSuchElementException:
            pass
        
        # Only return if we have question and answer
        if qa['question'] and qa['answer']:
            return qa
        return None
    
    def _parse_qa_alternative(self, max_qa: int) -> List[Dict]:
        """Alternative Q&A parsing for different page layouts."""
        driver = self.browser.get_driver()
        qa_pairs = []
        
        try:
            # Try finding questions directly
            questions = driver.find_elements(
                By.XPATH,
                "//*[contains(text(), 'Question:') or contains(@class, 'question')]"
            )
            
            for q_el in questions[:max_qa]:
                try:
                    # Get parent container
                    container = q_el.find_element(By.XPATH, './ancestor::div[contains(@class, "section")]')
                    
                    question_text = clean_html_tags(q_el.text)
                    
                    # Find answer nearby
                    try:
                        answer_el = container.find_element(
                            By.XPATH,
                            ".//*[contains(text(), 'Answer:') or contains(@class, 'answer')]"
                        )
                        answer_text = clean_html_tags(answer_el.text)
                        
                        if question_text and answer_text:
                            qa_pairs.append({
                                'question': question_text.replace('Question:', '').strip(),
                                'answer': filter_ad_phrases(answer_text.replace('Answer:', '').strip()),
                                'votes': None,
                                'answer_by': None,
                                'answer_date': None
                            })
                    except NoSuchElementException:
                        pass
                        
                except Exception:
                    continue
                    
        except Exception as e:
            logger.debug(f"Alternative Q&A parsing failed: {e}")
        
        return qa_pairs

