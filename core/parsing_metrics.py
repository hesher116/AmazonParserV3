"""Parsing metrics and statistics tracking"""
from typing import Dict, List, Optional
from collections import defaultdict, OrderedDict
from datetime import datetime
import json

from utils.logger import get_logger

logger = get_logger(__name__)


class ParsingMetrics:
    """Track parsing success metrics and selector statistics."""
    
    def __init__(self, max_selector_cache_size: int = 50):
        """
        Initialize metrics tracker.
        
        Args:
            max_selector_cache_size: Maximum number of selectors to cache
        """
        self.max_selector_cache_size = max_selector_cache_size
        
        # Selector success statistics: {selector: {'success_count': int, 'fail_count': int, 'last_used': datetime}}
        self.selector_stats: Dict[str, Dict] = defaultdict(lambda: {
            'success_count': 0,
            'fail_count': 0,
            'last_used': None
        })
        
        # Popular selectors (predefined list of most common selectors)
        self.popular_selectors = {
            'title': ['#productTitle', '#title', 'h1.a-size-large'],
            'brand': ['#bylineInfo', '.a-link-normal[href*="/stores/"]', '#brand'],
            'price': ['.a-price .a-offscreen', '#priceblock_ourprice', '#priceblock_dealprice'],
            'asin': ['[data-asin]', '#ASIN'],
            'reviews_summary': ['#acrPopover', '.a-icon-star span', '[data-hook="rating-out-of-text"]'],
            'qa_count': ['#askATFLink', '[data-hook="qa-questions-count"]'],
        }
        
        # Parsing success metrics
        self.parsing_metrics: Dict[str, Dict] = {
            'text': {'success': 0, 'partial': 0, 'failed': 0},
            'images': {'success': 0, 'partial': 0, 'failed': 0},
            'reviews': {'success': 0, 'partial': 0, 'failed': 0},
            'qa': {'success': 0, 'partial': 0, 'failed': 0},
        }
        
        # Fallback usage tracking
        self.fallback_usage: Dict[str, int] = defaultdict(int)
    
    def record_selector_success(self, selector: str, success: bool):
        """
        Record selector usage success/failure.
        
        Args:
            selector: CSS selector used
            success: True if selector found element, False otherwise
        """
        stats = self.selector_stats[selector]
        if success:
            stats['success_count'] += 1
        else:
            stats['fail_count'] += 1
        stats['last_used'] = datetime.now()
        
        # Limit cache size - remove least recently used if over limit
        if len(self.selector_stats) > self.max_selector_cache_size:
            self._trim_selector_cache()
    
    def get_prioritized_selectors(self, category: str) -> List[str]:
        """
        Get prioritized list of selectors for a category.
        
        Args:
            category: Category name (e.g., 'title', 'brand')
            
        Returns:
            List of selectors ordered by success rate
        """
        # Start with popular selectors for this category
        selectors = self.popular_selectors.get(category, [])
        
        # Add selectors from stats, sorted by success rate
        category_stats = {
            sel: stats for sel, stats in self.selector_stats.items()
            if category in sel.lower() or any(cat in sel for cat in ['title', 'brand', 'price'])
        }
        
        # Sort by success rate (success_count / (success_count + fail_count))
        sorted_stats = sorted(
            category_stats.items(),
            key=lambda x: (
                x[1]['success_count'] / max(1, x[1]['success_count'] + x[1]['fail_count']),
                x[1]['success_count']
            ),
            reverse=True
        )
        
        # Add top selectors from stats (avoid duplicates)
        for selector, _ in sorted_stats[:10]:
            if selector not in selectors:
                selectors.append(selector)
        
        return selectors
    
    def record_parsing_result(self, category: str, success: bool, partial: bool = False):
        """
        Record parsing result for a category.
        
        Args:
            category: Category name ('text', 'images', 'reviews', 'qa')
            success: True if parsing succeeded
            partial: True if partial results were obtained
        """
        if category in self.parsing_metrics:
            if success:
                self.parsing_metrics[category]['success'] += 1
            elif partial:
                self.parsing_metrics[category]['partial'] += 1
            else:
                self.parsing_metrics[category]['failed'] += 1
    
    def record_fallback(self, method: str):
        """
        Record fallback usage.
        
        Args:
            method: Fallback method used (e.g., 'selenium', 'alternative_selector')
        """
        self.fallback_usage[method] += 1
    
    def get_summary(self) -> Dict:
        """
        Get summary of all metrics.
        
        Returns:
            Dictionary with metrics summary
        """
        # Calculate selector success rates
        selector_success_rates = {}
        for selector, stats in self.selector_stats.items():
            total = stats['success_count'] + stats['fail_count']
            if total > 0:
                success_rate = stats['success_count'] / total
                selector_success_rates[selector] = {
                    'success_rate': success_rate,
                    'total_uses': total,
                    'last_used': stats['last_used'].isoformat() if stats['last_used'] else None
                }
        
        return {
            'parsing_metrics': self.parsing_metrics,
            'selector_success_rates': selector_success_rates,
            'fallback_usage': dict(self.fallback_usage),
            'total_selectors_tracked': len(self.selector_stats)
        }
    
    def _trim_selector_cache(self):
        """Remove least recently used selectors to stay within cache limit."""
        # Sort by last_used (oldest first)
        sorted_selectors = sorted(
            self.selector_stats.items(),
            key=lambda x: x[1]['last_used'] or datetime.min,
            reverse=False
        )
        
        # Remove oldest 20% if over limit
        to_remove = max(1, len(sorted_selectors) - self.max_selector_cache_size)
        for selector, _ in sorted_selectors[:to_remove]:
            del self.selector_stats[selector]
        
        logger.debug(f"Trimmed selector cache: removed {to_remove} selectors")
    
    def save_to_file(self, filepath: str):
        """Save metrics to JSON file."""
        try:
            summary = self.get_summary()
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(summary, f, indent=2, default=str)
            logger.info(f"Metrics saved to: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save metrics: {e}")
    
    def load_from_file(self, filepath: str):
        """Load metrics from JSON file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Restore selector stats
            if 'selector_success_rates' in data:
                for selector, stats in data['selector_success_rates'].items():
                    # Reconstruct from success rate and total
                    success_rate = stats.get('success_rate', 0)
                    total = stats.get('total_uses', 0)
                    self.selector_stats[selector] = {
                        'success_count': int(success_rate * total),
                        'fail_count': int((1 - success_rate) * total),
                        'last_used': datetime.fromisoformat(stats['last_used']) if stats.get('last_used') else None
                    }
            
            logger.info(f"Metrics loaded from: {filepath}")
        except Exception as e:
            logger.warning(f"Failed to load metrics: {e}")

