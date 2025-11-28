"""Configuration settings for Amazon Parser"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    """Application settings loaded from environment variables"""
    
    # Rate limiting
    RATE_LIMIT_MIN: float = float(os.getenv('AMAZON_PARSER_RATE_LIMIT_MIN', '1.5'))
    RATE_LIMIT_MAX: float = float(os.getenv('AMAZON_PARSER_RATE_LIMIT_MAX', '4.0'))
    
    # Retry settings
    MAX_RETRIES: int = int(os.getenv('AMAZON_PARSER_MAX_RETRIES', '3'))
    
    # Browser settings
    # Set to False for development to see browser window
    HEADLESS: bool = os.getenv('AMAZON_PARSER_HEADLESS', 'false').lower() == 'true'
    TIMEOUT: int = int(os.getenv('AMAZON_PARSER_TIMEOUT', '15'))
    
    # Logging
    LOG_LEVEL: str = os.getenv('AMAZON_PARSER_LOG_LEVEL', 'INFO')
    
    # Paths
    OUTPUT_DIR: str = os.getenv('AMAZON_PARSER_OUTPUT_DIR', 'outputs')
    DATABASE_PATH: str = os.getenv('AMAZON_PARSER_DATABASE_PATH', 'tasks.db')
    
    # Image download settings (reduced for faster parsing)
    IMAGE_DOWNLOAD_DELAY_MIN: float = 0.1
    IMAGE_DOWNLOAD_DELAY_MAX: float = 0.3
    
    # Window size
    WINDOW_WIDTH: int = 1920
    WINDOW_HEIGHT: int = 1080
    
    # User agents pool
    USER_AGENTS: list = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36 Edg/119.0.0.0',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0',
    ]
    
    # Ad phrases to filter
    AD_PHRASES: list = [
        'Shop our products',
        'Visit the store',
        'From the brand',
        'Sponsored',
        'Ad',
        'See all reviews',
        'Report an issue',
        'How customer reviews and ratings work',
    ]
    
    # Excluded URL patterns (video, 360, ads, icons)
    EXCLUDED_URL_PATTERNS: list = [
        '360',
        'video',
        'play-button',
        'sprite',
        'icon',
        'logo',
        'badge',
        'transparent',
        'grey-pixel',
        'blank',
        'loading',
        'spinner',
        '/sash/',  # SVG іконки Amazon
        '.svg',  # SVG файли
    ]
    
    # Image size limits
    MAX_IMAGE_SIZE: int = int(os.getenv('AMAZON_PARSER_MAX_IMAGE_SIZE', '10485760'))  # 10MB default
    
    # MD5 cache management
    MD5_CACHE_MAX_SIZE: int = int(os.getenv('AMAZON_PARSER_MD5_CACHE_MAX', '10000'))  # Max 10000 entries
    
    # Task cleanup
    TASK_CLEANUP_DAYS: int = int(os.getenv('AMAZON_PARSER_TASK_CLEANUP_DAYS', '30'))  # Keep tasks for 30 days
    
    # Selector cache
    SELECTOR_CACHE_ENABLED: bool = os.getenv('AMAZON_PARSER_SELECTOR_CACHE', 'true').lower() == 'true'
    
    # Performance logging
    PERFORMANCE_LOGGING: bool = os.getenv('AMAZON_PARSER_PERFORMANCE_LOGGING', 'true').lower() == 'true'

