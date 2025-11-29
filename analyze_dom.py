"""Script to analyze DOM dump and identify structure for parsing"""
import json
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from collections import defaultdict

from core.browser_pool import BrowserPool
from utils.logger import get_logger

logger = get_logger(__name__)


def analyze_dom_structure(url: str, output_file: str = None):
    """
    Analyze DOM structure of Amazon product page.
    
    Args:
        url: Amazon product URL
        output_file: Optional file to save analysis results
    """
    print("=" * 80)
    print("DOM STRUCTURE ANALYZER")
    print("=" * 80)
    print(f"URL: {url}\n")
    
    # Initialize browser
    browser = BrowserPool()
    
    try:
        # Navigate to page
        print("Loading page...")
        if not browser.navigate_to(url):
            print("❌ Failed to load page")
            return
        
        # Get DOM dump
        print("Getting DOM dump...")
        dom_dump = browser.get_page_source()
        soup = BeautifulSoup(dom_dump, 'html.parser')
        
        print(f"✓ DOM dump loaded: {len(dom_dump)} characters\n")
        
        # Analyze structure
        analysis = {
            'url': url,
            'dom_size': len(dom_dump),
            'sections': {}
        }
        
        # 1. Product Title
        print("=" * 80)
        print("1. PRODUCT TITLE")
        print("=" * 80)
        title_selectors = [
            '#productTitle',
            '#title',
            'h1.a-size-large',
            '[data-feature-name="title"]',
            '[data-automation-id="title"]',
            'h1',
        ]
        title_found = False
        for selector in title_selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                if text:
                    print(f"✓ Found with '{selector}': {text[:100]}...")
                    analysis['sections']['title'] = {
                        'selector': selector,
                        'text_preview': text[:200]
                    }
                    title_found = True
                    break
        if not title_found:
            print("❌ Title not found")
        
        # 2. Brand
        print("\n" + "=" * 80)
        print("2. BRAND")
        print("=" * 80)
        brand_selectors = [
            '#bylineInfo',
            '.a-link-normal[href*="/stores/"]',
            '#brand',
            '[data-feature-name="bylineInfo"]',
        ]
        brand_found = False
        for selector in brand_selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                if text:
                    print(f"✓ Found with '{selector}': {text}")
                    analysis['sections']['brand'] = {
                        'selector': selector,
                        'text': text
                    }
                    brand_found = True
                    break
        if not brand_found:
            print("❌ Brand not found")
        
        # 3. Price
        print("\n" + "=" * 80)
        print("3. PRICE")
        print("=" * 80)
        price_selectors = [
            '.a-price .a-offscreen',
            '#priceblock_ourprice',
            '#priceblock_dealprice',
            '#priceblock_saleprice',
            '.a-price-whole',
            '[data-a-color="price"] .a-offscreen',
            'span.a-price',
        ]
        price_found = False
        for selector in price_selectors:
            elems = soup.select(selector)
            for elem in elems:
                text = elem.get_text(strip=True)
                if text and '$' in text:
                    print(f"✓ Found with '{selector}': {text}")
                    if 'price' not in analysis['sections']:
                        analysis['sections']['price'] = []
                    analysis['sections']['price'].append({
                        'selector': selector,
                        'text': text
                    })
                    price_found = True
        if not price_found:
            print("❌ Price not found")
        
        # 4. Product Description
        print("\n" + "=" * 80)
        print("4. PRODUCT DESCRIPTION")
        print("=" * 80)
        desc_selectors = [
            '#productDescription_feature_div',
            '[data-feature-name="productDescription"]',
            '#aplus_feature_div',
            '.aplus-module',
        ]
        desc_found = False
        for selector in desc_selectors:
            elems = soup.select(selector)
            for elem in elems:
                # Check if has heading "Product Description"
                heading = elem.select_one('h2, h3')
                if heading:
                    heading_text = heading.get_text(strip=True).upper()
                    if 'PRODUCT DESCRIPTION' in heading_text:
                        text = elem.get_text(strip=True)
                        if len(text) > 50:
                            print(f"✓ Found with '{selector}'")
                            print(f"  Heading: {heading.get_text(strip=True)}")
                            print(f"  Text preview: {text[:200]}...")
                            print(f"  Full text length: {len(text)} chars")
                            analysis['sections']['product_description'] = {
                                'selector': selector,
                                'heading': heading.get_text(strip=True),
                                'text_preview': text[:500],
                                'full_length': len(text)
                            }
                            desc_found = True
                            break
            if desc_found:
                break
        if not desc_found:
            print("❌ Product Description not found")
        
        # 5. From the Brand
        print("\n" + "=" * 80)
        print("5. FROM THE BRAND")
        print("=" * 80)
        brand_story_selectors = [
            '#aplusBrandStory_feature_div',
            '[data-feature-name="brandStory"]',
            '.aplus-module',
        ]
        brand_story_found = False
        for selector in brand_story_selectors:
            elems = soup.select(selector)
            for elem in elems:
                heading = elem.select_one('h2, h3')
                if heading:
                    heading_text = heading.get_text(strip=True).upper()
                    if 'FROM THE BRAND' in heading_text or 'BRAND STORY' in heading_text:
                        text = elem.get_text(strip=True)
                        if len(text) > 50:
                            print(f"✓ Found with '{selector}'")
                            print(f"  Heading: {heading.get_text(strip=True)}")
                            print(f"  Text preview: {text[:200]}...")
                            analysis['sections']['from_the_brand'] = {
                                'selector': selector,
                                'heading': heading.get_text(strip=True),
                                'text_preview': text[:500],
                                'full_length': len(text)
                            }
                            brand_story_found = True
                            break
            if brand_story_found:
                break
        if not brand_story_found:
            print("❌ From the Brand not found")
        
        # 6. Product Details
        print("\n" + "=" * 80)
        print("6. PRODUCT DETAILS")
        print("=" * 80)
        details_selectors = [
            '#productDetails_detailBullets_sections1',
            '#detailBullets_feature_div',
            '#prodDetails',
        ]
        details_found = False
        for selector in details_selectors:
            elem = soup.select_one(selector)
            if elem:
                # Try table format
                table = elem.select_one('table')
                if table:
                    rows = table.select('tr')
                    print(f"✓ Found table with '{selector}': {len(rows)} rows")
                    data = {}
                    for row in rows[:5]:  # Show first 5 rows
                        cells = row.select('td, th')
                        if len(cells) >= 2:
                            key = cells[0].get_text(strip=True)
                            value = cells[1].get_text(strip=True)
                            print(f"  - {key}: {value[:50]}...")
                            data[key] = value[:100]
                    analysis['sections']['product_details'] = {
                        'selector': selector,
                        'format': 'table',
                        'rows_count': len(rows),
                        'sample_data': data
                    }
                    details_found = True
                    break
                # Try bullet format
                bullets = elem.select('li')
                if bullets:
                    print(f"✓ Found bullets with '{selector}': {len(bullets)} items")
                    for bullet in bullets[:5]:  # Show first 5
                        text = bullet.get_text(strip=True)
                        print(f"  - {text[:80]}...")
                    analysis['sections']['product_details'] = {
                        'selector': selector,
                        'format': 'bullets',
                        'items_count': len(bullets),
                        'sample_items': [b.get_text(strip=True)[:100] for b in bullets[:5]]
                    }
                    details_found = True
                    break
        if not details_found:
            print("❌ Product Details not found")
        
        # 7. Important Information
        print("\n" + "=" * 80)
        print("7. IMPORTANT INFORMATION")
        print("=" * 80)
        important_selectors = [
            '#important-information',
            '[data-feature-name="importantInformation"]',
        ]
        important_found = False
        for selector in important_selectors:
            elem = soup.select_one(selector)
            if elem:
                print(f"✓ Found with '{selector}'")
                
                # Find all subsections
                subsections = elem.select('.a-section')
                print(f"  Subsections found: {len(subsections)}")
                
                subsection_data = []
                for i, sub in enumerate(subsections[:10]):  # Show first 10
                    heading = sub.select_one('h4, h5, .a-text-bold, strong')
                    content = sub.select_one('.content, p, span, div')
                    
                    if heading:
                        heading_text = heading.get_text(strip=True)
                        content_text = content.get_text(strip=True) if content else ""
                        print(f"  [{i+1}] {heading_text}: {content_text[:80]}...")
                        subsection_data.append({
                            'heading': heading_text,
                            'content_preview': content_text[:200]
                        })
                
                analysis['sections']['important_information'] = {
                    'selector': selector,
                    'subsections_count': len(subsections),
                    'subsections': subsection_data
                }
                important_found = True
                break
        if not important_found:
            print("❌ Important Information not found")
        
        # 8. Sustainability Features
        print("\n" + "=" * 80)
        print("8. SUSTAINABILITY FEATURES")
        print("=" * 80)
        sustainability_keywords = [
            'sustainability', 'compact by design', 'climate pledge',
            'packaging efficiency', 'certification'
        ]
        
        # Check in Important Information
        important_elem = soup.select_one('#important-information')
        sustainability_found = False
        
        if important_elem:
            subsections = important_elem.select('.a-section')
            for sub in subsections:
                heading = sub.select_one('h4, h5, .a-text-bold, strong')
                if heading:
                    heading_text = heading.get_text(strip=True).upper()
                    if any(kw.upper() in heading_text for kw in sustainability_keywords):
                        content = sub.select_one('.content, p, span')
                        content_text = content.get_text(strip=True) if content else ""
                        print(f"✓ Found in Important Information:")
                        print(f"  Heading: {heading.get_text(strip=True)}")
                        print(f"  Content: {content_text[:200]}...")
                        analysis['sections']['sustainability'] = {
                            'location': 'important_information',
                            'heading': heading.get_text(strip=True),
                            'content_preview': content_text[:500]
                        }
                        sustainability_found = True
        
        # Also check standalone
        sustainability_selectors = [
            '[data-feature-name="sustainability"]',
            '#sustainability_feature_div',
            '.sustainability-feature',
        ]
        for selector in sustainability_selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                if text:
                    print(f"✓ Found standalone with '{selector}'")
                    print(f"  Text: {text[:200]}...")
                    analysis['sections']['sustainability'] = {
                        'location': 'standalone',
                        'selector': selector,
                        'text_preview': text[:500]
                    }
                    sustainability_found = True
                    break
        
        if not sustainability_found:
            print("❌ Sustainability Features not found")
        
        # 9. Customers Say / Customer Reviews (should NOT be in text parser)
        print("\n" + "=" * 80)
        print("9. CUSTOMERS SAY / CUSTOMER REVIEWS (should be excluded)")
        print("=" * 80)
        customers_say_selectors = [
            '[data-hook="cr-summarization-attribute"]',
            '.cr-lighthouse-term',
        ]
        customers_say_found = False
        for selector in customers_say_selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                if text:
                    print(f"⚠️  Found 'Customers say' with '{selector}': {text[:100]}...")
                    print("   ⚠️  This should NOT be in Important Information!")
                    analysis['sections']['customers_say'] = {
                        'selector': selector,
                        'text': text[:200],
                        'note': 'Should be excluded from Important Information'
                    }
                    customers_say_found = True
        
        # Check if in Important Information
        if important_elem:
            important_text = important_elem.get_text().upper()
            if 'CUSTOMERS SAY' in important_text or 'CUSTOMER REVIEWS' in important_text:
                print("⚠️  'Customers say' or 'Customer reviews' found in Important Information section!")
                print("   ⚠️  This should be excluded!")
        
        if not customers_say_found:
            print("✓ No 'Customers say' found (good)")
        
        # 10. About This Item
        print("\n" + "=" * 80)
        print("10. ABOUT THIS ITEM")
        print("=" * 80)
        about_selectors = [
            '#feature-bullets ul',
            '#productFactsDesktopExpander ul',
            '[data-feature-name="featurebullets"] ul',
        ]
        about_found = False
        for selector in about_selectors:
            elem = soup.select_one(selector)
            if elem:
                items = elem.select('li')
                if items:
                    print(f"✓ Found with '{selector}': {len(items)} items")
                    for i, item in enumerate(items[:5]):  # Show first 5
                        text = item.get_text(strip=True)
                        print(f"  [{i+1}] {text[:80]}...")
                    analysis['sections']['about_this_item'] = {
                        'selector': selector,
                        'items_count': len(items),
                        'sample_items': [item.get_text(strip=True)[:100] for item in items[:5]]
                    }
                    about_found = True
                    break
        if not about_found:
            print("❌ About This Item not found")
        
        # 11. Technical Details
        print("\n" + "=" * 80)
        print("11. TECHNICAL DETAILS")
        print("=" * 80)
        tech_selectors = [
            '#productDetails_techSpec_section_1',
            '#techSpecifications',
            '[data-feature-name="technicalSpecifications"]',
        ]
        tech_found = False
        for selector in tech_selectors:
            elem = soup.select_one(selector)
            if elem:
                table = elem.select_one('table')
                if table:
                    rows = table.select('tr')
                    print(f"✓ Found with '{selector}': {len(rows)} rows")
                    for row in rows[:5]:
                        cells = row.select('td, th')
                        if len(cells) >= 2:
                            key = cells[0].get_text(strip=True)
                            value = cells[1].get_text(strip=True)
                            print(f"  - {key}: {value[:50]}...")
                    analysis['sections']['technical_details'] = {
                        'selector': selector,
                        'rows_count': len(rows)
                    }
                    tech_found = True
                    break
        if not tech_found:
            print("❌ Technical Details not found")
        
        # Summary
        print("\n" + "=" * 80)
        print("SUMMARY")
        print("=" * 80)
        print(f"Total sections found: {len(analysis['sections'])}")
        for section_name in analysis['sections']:
            print(f"  ✓ {section_name}")
        
        # Save to file
        if output_file:
            output_path = Path(output_file)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(analysis, f, indent=2, ensure_ascii=False)
            print(f"\n✓ Analysis saved to: {output_file}")
        
        # Save DOM dump for manual inspection
        dom_file = output_file.replace('.json', '_dom.html') if output_file else 'dom_dump.html'
        with open(dom_file, 'w', encoding='utf-8') as f:
            f.write(dom_dump)
        print(f"✓ DOM dump saved to: {dom_file}")
        
    finally:
        browser.close_driver()


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python analyze_dom.py <amazon_url> [output_file.json]")
        print("\nExample:")
        print("  python analyze_dom.py 'https://www.amazon.com/dp/B07W442DN7' analysis.json")
        sys.exit(1)
    
    url = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'dom_analysis.json'
    
    analyze_dom_structure(url, output_file)

