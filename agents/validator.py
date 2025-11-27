"""Validator Agent - Validates collected data"""
import os
from typing import Dict, List
from pathlib import Path

from utils.logger import get_logger

logger = get_logger(__name__)


class ValidatorAgent:
    """Agent for validating parsed data quality."""
    
    # Required fields for complete data
    REQUIRED_FIELDS = ['title', 'asin', 'price']
    
    # Optional but important fields
    IMPORTANT_FIELDS = ['brand', 'about_this_item', 'product_overview']
    
    def validate(self, results: Dict, output_dir: str = None) -> Dict:
        """
        Validate collected results.
        
        Args:
            results: Dictionary with all parsing results
            output_dir: Output directory to check for images
            
        Returns:
            Validation report dictionary
        """
        logger.info("Starting validation...")
        
        report = {
            'is_valid': True,
            'completeness_score': 0.0,
            'missing_required': [],
            'missing_important': [],
            'warnings': [],
            'image_stats': {},
            'summary': {}
        }
        
        try:
            # Validate text data
            text_results = results.get('text', {})
            self._validate_required_fields(text_results, report)
            self._validate_important_fields(text_results, report)
            
            # Validate images
            if output_dir:
                self._validate_images(output_dir, report)
            
            image_results = results.get('images', {})
            if image_results:
                self._validate_image_results(image_results, report)
            
            # Validate reviews
            review_results = results.get('reviews', {})
            if review_results:
                self._validate_reviews(review_results, report)
            
            # Validate Q&A
            qa_results = results.get('qa', {})
            if qa_results:
                self._validate_qa(qa_results, report)
            
            # Validate variants
            variant_results = results.get('variants', {})
            if variant_results:
                self._validate_variants(variant_results, report)
            
            # Calculate completeness score
            report['completeness_score'] = self._calculate_completeness(results, report)
            
            # Generate summary
            report['summary'] = self._generate_summary(results, report)
            
            logger.info(f"Validation complete: score={report['completeness_score']:.1f}%")
            
        except Exception as e:
            logger.error(f"Validation error: {e}")
            report['warnings'].append(f"Validation error: {str(e)}")
        
        return report
    
    def _validate_required_fields(self, text_results: Dict, report: Dict):
        """Check required fields."""
        for field in self.REQUIRED_FIELDS:
            value = text_results.get(field)
            
            if field == 'price':
                # Price is a dict, check for current_price
                if not value or not value.get('current_price'):
                    report['missing_required'].append(field)
                    report['is_valid'] = False
            elif not value:
                report['missing_required'].append(field)
                report['is_valid'] = False
        
        if report['missing_required']:
            logger.warning(f"Missing required fields: {report['missing_required']}")
    
    def _validate_important_fields(self, text_results: Dict, report: Dict):
        """Check important but optional fields."""
        for field in self.IMPORTANT_FIELDS:
            value = text_results.get(field)
            
            if not value or (isinstance(value, (list, dict)) and len(value) == 0):
                report['missing_important'].append(field)
        
        if report['missing_important']:
            logger.debug(f"Missing important fields: {report['missing_important']}")
    
    def _validate_images(self, output_dir: str, report: Dict):
        """Validate saved images."""
        stats = {
            'hero': 0,
            'product': 0,
            'aplus_brand': 0,
            'aplus_product': 0,
            'qa_images': 0,
            'total': 0
        }
        
        base_path = Path(output_dir)
        
        if base_path.exists():
            # Count images in each directory
            for subdir, key in [
                ('hero', 'hero'),
                ('product', 'product'),
                ('aplus_brand', 'aplus_brand'),
                ('aplus_product', 'aplus_product'),
                ('QAImages', 'qa_images')
            ]:
                dir_path = base_path / subdir
                if dir_path.exists():
                    count = len([f for f in dir_path.iterdir() 
                               if f.is_file() and f.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']])
                    stats[key] = count
                    stats['total'] += count
        
        report['image_stats'] = stats
        
        # Warnings for missing images
        if stats['hero'] == 0:
            report['warnings'].append("No hero image found")
        
        if stats['product'] == 0 and stats['hero'] == 0:
            report['warnings'].append("No product images found")
    
    def _validate_image_results(self, image_results: Dict, report: Dict):
        """Validate image parsing results."""
        if image_results.get('errors'):
            for error in image_results['errors']:
                report['warnings'].append(f"Image parsing error: {error}")
    
    def _validate_reviews(self, review_results: Dict, report: Dict):
        """Validate review data."""
        summary = review_results.get('summary', {})
        reviews = review_results.get('reviews', [])
        
        # Check rating format
        rating = summary.get('rating')
        if rating:
            try:
                rating_float = float(rating)
                if rating_float < 0 or rating_float > 5:
                    report['warnings'].append(f"Invalid rating value: {rating}")
            except ValueError:
                report['warnings'].append(f"Invalid rating format: {rating}")
        
        # Check for duplicate reviews
        seen_texts = set()
        duplicate_count = 0
        for review in reviews:
            text = review.get('text', '')
            if text in seen_texts:
                duplicate_count += 1
            else:
                seen_texts.add(text)
        
        if duplicate_count > 0:
            report['warnings'].append(f"Found {duplicate_count} duplicate reviews")
        
        if review_results.get('errors'):
            for error in review_results['errors']:
                report['warnings'].append(f"Review parsing error: {error}")
    
    def _validate_qa(self, qa_results: Dict, report: Dict):
        """Validate Q&A data."""
        qa_pairs = qa_results.get('qa_pairs', [])
        
        # Check for empty answers
        empty_answers = sum(1 for qa in qa_pairs if not qa.get('answer'))
        if empty_answers > 0:
            report['warnings'].append(f"Found {empty_answers} Q&A pairs with empty answers")
        
        if qa_results.get('errors'):
            for error in qa_results['errors']:
                report['warnings'].append(f"Q&A parsing error: {error}")
    
    def _validate_variants(self, variant_results: Dict, report: Dict):
        """Validate variant data."""
        variants = variant_results.get('variants', [])
        
        # Check for variants without ASIN
        no_asin = sum(1 for v in variants if not v.get('asin'))
        if no_asin > 0:
            report['warnings'].append(f"Found {no_asin} variants without ASIN")
        
        if variant_results.get('errors'):
            for error in variant_results['errors']:
                report['warnings'].append(f"Variant parsing error: {error}")
    
    def _calculate_completeness(self, results: Dict, report: Dict) -> float:
        """Calculate overall completeness score (0-100)."""
        score = 0.0
        max_score = 0.0
        
        # Text fields scoring
        text_results = results.get('text', {})
        
        # Required fields (40 points total)
        for field in self.REQUIRED_FIELDS:
            max_score += 13.33
            value = text_results.get(field)
            if field == 'price':
                if value and value.get('current_price'):
                    score += 13.33
            elif value:
                score += 13.33
        
        # Important fields (30 points total)
        for field in self.IMPORTANT_FIELDS:
            max_score += 10
            value = text_results.get(field)
            if value and (not isinstance(value, (list, dict)) or len(value) > 0):
                score += 10
        
        # Images (15 points)
        max_score += 15
        image_stats = report.get('image_stats', {})
        if image_stats.get('total', 0) > 0:
            score += 5
        if image_stats.get('hero', 0) > 0:
            score += 5
        if image_stats.get('product', 0) > 0:
            score += 5
        
        # Reviews (10 points)
        max_score += 10
        review_results = results.get('reviews', {})
        if review_results.get('summary', {}).get('rating'):
            score += 5
        if review_results.get('reviews'):
            score += 5
        
        # Q&A (5 points)
        max_score += 5
        qa_results = results.get('qa', {})
        if qa_results.get('qa_pairs'):
            score += 5
        
        return (score / max_score * 100) if max_score > 0 else 0
    
    def _generate_summary(self, results: Dict, report: Dict) -> Dict:
        """Generate validation summary."""
        text_results = results.get('text', {})
        image_results = results.get('images', {})
        review_results = results.get('reviews', {})
        qa_results = results.get('qa', {})
        variant_results = results.get('variants', {})
        
        summary = {
            'product_title': text_results.get('title', 'Unknown'),
            'asin': text_results.get('asin', 'Unknown'),
            'has_price': bool(text_results.get('price', {}).get('current_price')),
            'image_count': report.get('image_stats', {}).get('total', 0),
            'review_count': len(review_results.get('reviews', [])),
            'rating': review_results.get('summary', {}).get('rating'),
            'qa_count': len(qa_results.get('qa_pairs', [])),
            'variant_count': len(variant_results.get('variants', [])),
            'warning_count': len(report.get('warnings', [])),
            'completeness': f"{report.get('completeness_score', 0):.1f}%"
        }
        
        return summary

