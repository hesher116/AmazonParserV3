"""Q&A Parser Agent - Parses questions and answers"""
from typing import Dict, List, Optional

from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException

from agents.base_parser import BaseParser
from core.browser_pool import BrowserPool
from utils.text_utils import clean_html_tags, filter_ad_phrases
from utils.logger import get_logger

logger = get_logger(__name__)


class QAParserAgent(BaseParser):
    """Agent for parsing Q&A from Amazon product page."""
    
    def __init__(self, browser_pool: BrowserPool, dom_soup: Optional[BeautifulSoup] = None):
        super().__init__(browser_pool, dom_soup)
    
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
        selectors = [
            '#askATFLink',
            '[data-hook="qa-questions-count"]',
            '.a-section.askInlineWidget a',
        ]
        
        for selector in selectors:
            element = self.find_element_by_selector(selector, use_dom=True)
            if element:
                text = self.get_text_from_element(element)
                text = clean_html_tags(text)
                if text:
                    return text
        
        return None
    
    def _parse_qa_pairs(self, max_qa: int) -> List[Dict]:
        """
        Parse Q&A pairs from the page.
        
        Args:
            max_qa: Maximum pairs to parse
            
        Returns:
            List of Q&A dictionaries
        """
        qa_pairs = []
        
        # Find Q&A items directly from DOM (no scroll needed - data is already in DOM dump)
        qa_selectors = [
            '.a-section.askTeaserQuestions > div',
            '[data-hook="ask-content"] .a-section',
            '.askInlineWidget .a-fixed-left-grid',
        ]
        
        for selector in qa_selectors:
            qa_elements = self.find_elements_by_selector(selector, use_dom=True)
                
            if qa_elements:
                for element in qa_elements[:max_qa]:
                    qa_pair = self._parse_single_qa(element)
                    if qa_pair:
                        qa_pairs.append(qa_pair)
                if qa_pairs:
                    break
        
        # Alternative parsing for different layout
        if not qa_pairs:
            qa_pairs = self._parse_qa_alternative(max_qa)
        
        return qa_pairs
    
    def _parse_single_qa(self, element) -> Dict:
        """Parse a single Q&A element (works with both BeautifulSoup and Selenium)."""
        qa = {
            'question': None,
            'answer': None,
            'votes': None,
            'answer_by': None,
            'answer_date': None
        }
        
        if element is None:
            return None
        
        # Question
        question_selectors = [
            '.a-text-bold, .askTeaserQuestion',
            'a[href*="ask/questions"]',
            '.a-link-normal span',
        ]
        
        for selector in question_selectors:
            q_el = None
            if hasattr(element, 'select_one'):  # BeautifulSoup
                q_el = element.select_one(selector)
            elif hasattr(element, 'find_element'):  # Selenium
                try:
                    q_el = element.find_element(By.CSS_SELECTOR, selector)
                except:
                    continue
            
            if q_el:
                text = self.get_text_from_element(q_el)
                text = clean_html_tags(text)
                if text and ('?' in text or text.startswith('Q:')):
                    qa['question'] = text.replace('Q:', '').strip()
                    break
        
        # Answer
        answer_selectors = [
            '.askLongText, .askTeaserAnswer',
            '.a-size-base:not(.a-text-bold)',
        ]
        
        for selector in answer_selectors:
            a_el = None
            if hasattr(element, 'select_one'):  # BeautifulSoup
                a_el = element.select_one(selector)
            elif hasattr(element, 'find_element'):  # Selenium
                try:
                    a_el = element.find_element(By.CSS_SELECTOR, selector)
                except:
                    continue
            
            if a_el:
                text = self.get_text_from_element(a_el)
                text = clean_html_tags(text)
                text = filter_ad_phrases(text)
                if text and len(text) > 10:
                    qa['answer'] = text.replace('A:', '').strip()
                    break
        
        # Votes
        votes_el = None
        if hasattr(element, 'select_one'):  # BeautifulSoup
            votes_el = element.select_one('.askVoteCount')
        elif hasattr(element, 'find_element'):  # Selenium
            try:
                votes_el = element.find_element(By.CSS_SELECTOR, '.askVoteCount')
            except:
                pass
        
        if votes_el:
            qa['votes'] = clean_html_tags(self.get_text_from_element(votes_el))
        
        # Answer by / Date
        info_el = None
        if hasattr(element, 'select_one'):  # BeautifulSoup
            info_el = element.select_one('.a-color-tertiary, .a-size-small.a-color-secondary')
        elif hasattr(element, 'find_element'):  # Selenium
            try:
                info_el = element.find_element(By.CSS_SELECTOR, '.a-color-tertiary, .a-size-small.a-color-secondary')
            except:
                pass
        
        if info_el:
            info_text = clean_html_tags(self.get_text_from_element(info_el))
            if 'by' in info_text.lower():
                qa['answer_by'] = info_text
        
        # Only return if we have question and answer
        if qa['question'] and qa['answer']:
            return qa
        return None
    
    def _parse_qa_alternative(self, max_qa: int) -> List[Dict]:
        """Alternative Q&A parsing for different page layouts."""
        qa_pairs = []
        
        try:
            # Try finding questions directly from DOM
            if self.dom_soup:
                # Use BeautifulSoup for DOM parsing - simplified approach
                # Find all text nodes containing "Question:"
                questions = self.dom_soup.find_all(string=lambda text: text and 'Question:' in str(text))
                # For now, skip DOM parsing for alternative method (too complex)
                # Fallback to Selenium
                questions = None
            
            # Fallback to Selenium
            if not questions:
                driver = self.browser.get_driver()
                try:
                    questions = driver.find_elements(
                        By.XPATH,
                        "//*[contains(text(), 'Question:') or contains(@class, 'question')]"
                    )
                except:
                    return qa_pairs
            
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

