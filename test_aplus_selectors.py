"""
Скрипт для перевірки селекторів A+ контенту на різних товарах Amazon.
Допомагає знайти універсальні селектори для швидшого парсингу.
"""
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from core.browser_pool import BrowserPool
from utils.logger import get_logger

logger = get_logger(__name__)


# Список тестових товарів (додайте свої URL)
TEST_PRODUCTS = [
    "https://www.amazon.com/dp/B0B2RN691M/ref=sspa_sp_vse_RVP_detail_7?sp_csd=d2lkZ2V0TmFtZT1zcF92c2VfUlZQX2RldGFpbA&th=1",
    "https://www.amazon.com/dp/B08N471RKG?th=1",
    "https://www.amazon.com/dp/B0CS26XRVX?th=1",
    "https://www.amazon.com/dp/B07W442DN7/?th=1",
    "https://www.amazon.com/Color-Dream-Supernatural-Spray-Multi-award-winning/dp/B073CWSQ51?pd_rd_w=9LZh9&content-id=amzn1.sym.f8779a1a-2190-4fac-ac85-1580456e8fdc&pf_rd_p=f8779a1a-2190-4fac-ac85-1580456e8fdc&pf_rd_r=2EAVX3573W213E5MVFG9&pd_rd_wg=T29KJ&pd_rd_r=1c445fb0-57b5-4601-90f9-f5cd5090c632&pd_rd_i=B073CWSQ51&ref_=dlx_deals_sh_B073CWSQ51&th=1",
    "https://www.amazon.com/PlayStation%C2%AE5-console-slim-PlayStation-5/dp/B0CL61F39H?ref=dlx_black_dg_dcl_B0CL61F39H_dt_sl7_65_pi&pf_rd_r=2EAVX3573W213E5MVFG9&pf_rd_p=3e031ad7-cedb-4fba-99e3-2ad8e7189565&th=1",   
    "https://www.amazon.com/PlayStation-DualSense%C2%AE-Wireless-Controller-White-5/dp/B0CQKLS4RP/ref=pd_bxgy_thbs_d_sccl_1/145-3852893-6471112?pd_rd_w=JMMLX&content-id=amzn1.sym.dcf559c6-d374-405e-a13e-133e852d81e1&pf_rd_p=dcf559c6-d374-405e-a13e-133e852d81e1&pf_rd_r=SH08ZSBE0F3B4T9TV671&pd_rd_wg=oh9TA&pd_rd_r=3197b02d-5c8b-43ce-98e8-924a4a3280f6&pd_rd_i=B0CQKLS4RP&th=1",
    "https://www.amazon.com/Apple-Headphones-Cancellation-Transparency-Personalized/dp/B0DGJ7HYG1/ref=pd_vtp_h_pd_vtp_h_d_sccl_3/145-3852893-6471112?pd_rd_w=BkZYl&content-id=amzn1.sym.e56a2492-63c9-43e2-8ff2-0f40df559930&pf_rd_p=e56a2492-63c9-43e2-8ff2-0f40df559930&pf_rd_r=SH08ZSBE0F3B4T9TV671&pd_rd_wg=oh9TA&pd_rd_r=3197b02d-5c8b-43ce-98e8-924a4a3280f6&pd_rd_i=B0DGJ7HYG1&psc=1", 
    "https://www.amazon.com/dp/B0CWPK46FF/ref=sspa_dk_detail_3?psc=1&pd_rd_i=B0CWPK46FF&pd_rd_w=8H195&content-id=amzn1.sym.85ceacba-39b1-4243-8f28-2e014f9512c7&pf_rd_p=85ceacba-39b1-4243-8f28-2e014f9512c7&pf_rd_r=6XJXNH9D820DQZPV6494&pd_rd_wg=23BoA&pd_rd_r=0ab96cc8-2f40-4854-995f-7fcd6c38244d&sp_csd=d2lkZ2V0TmFtZT1zcF9kZXRhaWxfdGhlbWF0aWM", 
    "https://www.amazon.com/Marc-Anthony-Leave-In-Conditioner-Detangler-Spray/dp/B076FHJ3K5/ref=pd_bxgy_thbs_d_sccl_2/145-3852893-6471112?pd_rd_w=ZKTl4&content-id=amzn1.sym.dcf559c6-d374-405e-a13e-133e852d81e1&pf_rd_p=dcf559c6-d374-405e-a13e-133e852d81e1&pf_rd_r=WGJPRXT9HXBJMCQPJ5GG&pd_rd_wg=gup2U&pd_rd_r=0cea4fc5-d977-4221-8291-a9b650ed95b3&pd_rd_i=B076FHJ3K5&th=1"
]

# Селектори для перевірки
BRAND_SELECTORS = [
    '#aplusBrandStory_feature_div',
    '[data-feature-name="aplusBrandStory"]',
    '#aplus_feature_div',
    '#aplus',
    '.aplus-module',
    '[data-feature-name="aplus"]',
    '[id*="brand"]',
    '[id*="Brand"]',
    '.aplus-brand',
    '#brandStory',
]

PRODUCT_SELECTORS = [
    '#productDescription_feature_div',
    '[data-feature-name="productDescription"]',
    '#aplus_feature_div',
    '#aplus',
    '.aplus-module',
    '[data-feature-name="aplus"]',
    '[id*="productDescription"]',
    '[id*="ProductDescription"]',
    '.aplus-product',
    '#productDescription',
]


def test_selectors_on_product(browser, url: str) -> dict:
    """Тестує всі селектори на одному товарі."""
    logger.info(f"\n{'='*80}")
    logger.info(f"Testing product: {url}")
    logger.info(f"{'='*80}")
    
    results = {
        'url': url,
        'brand_selectors': {},
        'product_selectors': {},
        'brand_sections_found': 0,
        'product_sections_found': 0,
    }
    
    try:
        # Navigate to product
        if not browser.navigate_to(url):
            logger.error(f"Failed to navigate to {url}")
            return results
        
        driver = browser.get_driver()
        time.sleep(2)  # Wait for page to fully load
        
        # Test brand selectors
        logger.info("\n--- Testing BRAND selectors ---")
        for selector in BRAND_SELECTORS:
            try:
                start_time = time.time()
                sections = driver.find_elements(By.CSS_SELECTOR, selector)
                elapsed = time.time() - start_time
                
                count = len(sections)
                results['brand_selectors'][selector] = {
                    'count': count,
                    'time': elapsed,
                    'found': count > 0
                }
                
                if count > 0:
                    # Check if section contains "From the brand" text
                    has_brand_text = False
                    for section in sections[:1]:  # Check first section only
                        try:
                            text = section.text[:500].upper()
                            if 'FROM THE BRAND' in text or 'FROM THE BRAND' in text:
                                has_brand_text = True
                                break
                        except:
                            pass
                    
                    logger.info(f"  ✓ {selector}: {count} sections found ({elapsed:.3f}s) [Brand text: {has_brand_text}]")
                    if has_brand_text:
                        results['brand_sections_found'] += count
                else:
                    logger.debug(f"  ✗ {selector}: 0 sections ({elapsed:.3f}s)")
                    
            except Exception as e:
                logger.warning(f"  ✗ {selector}: Error - {e}")
                results['brand_selectors'][selector] = {
                    'count': 0,
                    'time': 0,
                    'found': False,
                    'error': str(e)
                }
        
        # Test product selectors
        logger.info("\n--- Testing PRODUCT selectors ---")
        for selector in PRODUCT_SELECTORS:
            try:
                start_time = time.time()
                sections = driver.find_elements(By.CSS_SELECTOR, selector)
                elapsed = time.time() - start_time
                
                count = len(sections)
                results['product_selectors'][selector] = {
                    'count': count,
                    'time': elapsed,
                    'found': count > 0
                }
                
                if count > 0:
                    # Check if section contains product description markers
                    has_product_text = False
                    for section in sections[:1]:  # Check first section only
                        try:
                            text = section.text[:500].upper()
                            if 'PRODUCT DESCRIPTION' in text or 'PRODUCT DETAILS' in text:
                                has_product_text = True
                                break
                        except:
                            pass
                    
                    logger.info(f"  ✓ {selector}: {count} sections found ({elapsed:.3f}s) [Product text: {has_product_text}]")
                    if has_product_text:
                        results['product_sections_found'] += count
                else:
                    logger.debug(f"  ✗ {selector}: 0 sections ({elapsed:.3f}s)")
                    
            except Exception as e:
                logger.warning(f"  ✗ {selector}: Error - {e}")
                results['product_selectors'][selector] = {
                    'count': 0,
                    'time': 0,
                    'found': False,
                    'error': str(e)
                }
        
        # Summary
        logger.info(f"\n--- Summary for {url} ---")
        logger.info(f"Brand sections found: {results['brand_sections_found']}")
        logger.info(f"Product sections found: {results['product_sections_found']}")
        
    except Exception as e:
        logger.error(f"Error testing product {url}: {e}")
        import traceback
        logger.error(traceback.format_exc())
    
    return results


def analyze_results(all_results: list) -> dict:
    """Аналізує результати тестування і знаходить найкращі селектори."""
    logger.info(f"\n{'='*80}")
    logger.info("ANALYZING RESULTS")
    logger.info(f"{'='*80}")
    
    # Count how many times each selector found sections
    brand_stats = {}
    product_stats = {}
    
    for result in all_results:
        # Brand selectors
        for selector, data in result['brand_selectors'].items():
            if selector not in brand_stats:
                brand_stats[selector] = {
                    'found_count': 0,
                    'total_count': 0,
                    'total_time': 0,
                    'products': []
                }
            
            brand_stats[selector]['total_count'] += data['count']
            brand_stats[selector]['total_time'] += data.get('time', 0)
            if data['found']:
                brand_stats[selector]['found_count'] += 1
                brand_stats[selector]['products'].append(result['url'])
        
        # Product selectors
        for selector, data in result['product_selectors'].items():
            if selector not in product_stats:
                product_stats[selector] = {
                    'found_count': 0,
                    'total_count': 0,
                    'total_time': 0,
                    'products': []
                }
            
            product_stats[selector]['total_count'] += data['count']
            product_stats[selector]['total_time'] += data.get('time', 0)
            if data['found']:
                product_stats[selector]['found_count'] += 1
                product_stats[selector]['products'].append(result['url'])
    
    # Find best selectors (found in most products, fastest)
    logger.info("\n--- BEST BRAND SELECTORS ---")
    brand_sorted = sorted(
        brand_stats.items(),
        key=lambda x: (x[1]['found_count'], -x[1]['total_time']),
        reverse=True
    )
    
    for selector, stats in brand_sorted[:5]:
        avg_time = stats['total_time'] / len(all_results) if all_results else 0
        logger.info(f"  {selector}:")
        logger.info(f"    Found in {stats['found_count']}/{len(all_results)} products")
        logger.info(f"    Total sections: {stats['total_count']}")
        logger.info(f"    Avg time: {avg_time:.3f}s")
        logger.info(f"    Products: {stats['products'][:3]}...")
    
    logger.info("\n--- BEST PRODUCT SELECTORS ---")
    product_sorted = sorted(
        product_stats.items(),
        key=lambda x: (x[1]['found_count'], -x[1]['total_time']),
        reverse=True
    )
    
    for selector, stats in product_sorted[:5]:
        avg_time = stats['total_time'] / len(all_results) if all_results else 0
        logger.info(f"  {selector}:")
        logger.info(f"    Found in {stats['found_count']}/{len(all_results)} products")
        logger.info(f"    Total sections: {stats['total_count']}")
        logger.info(f"    Avg time: {avg_time:.3f}s")
        logger.info(f"    Products: {stats['products'][:3]}...")
    
    # Recommendations
    logger.info("\n--- RECOMMENDATIONS ---")
    best_brand = brand_sorted[0][0] if brand_sorted and brand_sorted[0][1]['found_count'] > 0 else None
    best_product = product_sorted[0][0] if product_sorted and product_sorted[0][1]['found_count'] > 0 else None
    
    if best_brand:
        logger.info(f"Recommended BRAND selector: {best_brand}")
    if best_product:
        logger.info(f"Recommended PRODUCT selector: {best_product}")
    
    return {
        'brand_stats': brand_stats,
        'product_stats': product_stats,
        'best_brand': best_brand,
        'best_product': best_product
    }


def main():
    """Головна функція для запуску тестування."""
    if len(TEST_PRODUCTS) < 2:
        logger.warning("Please add at least 2 product URLs to TEST_PRODUCTS list!")
        logger.info("Edit this file and add product URLs to test.")
        return
    
    logger.info(f"Starting A+ selector testing on {len(TEST_PRODUCTS)} products...")
    
    browser = BrowserPool()
    all_results = []
    
    try:
        for i, url in enumerate(TEST_PRODUCTS, 1):
            logger.info(f"\n\nProcessing product {i}/{len(TEST_PRODUCTS)}")
            result = test_selectors_on_product(browser, url)
            all_results.append(result)
            
            # Small delay between products
            if i < len(TEST_PRODUCTS):
                time.sleep(2)
        
        # Analyze results
        analysis = analyze_results(all_results)
        
        logger.info("\n" + "="*80)
        logger.info("TESTING COMPLETE")
        logger.info("="*80)
        
    except KeyboardInterrupt:
        logger.info("\n\nTesting interrupted by user")
    except Exception as e:
        logger.error(f"Error during testing: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        browser.close_driver()
        logger.info("Browser closed")


if __name__ == "__main__":
    main()

