"""Structured logging for Amazon Parser"""
import logging
import sys
from datetime import datetime
from pathlib import Path

try:
    from colorama import Fore, Back, Style, init
    init(autoreset=True)
    COLORAMA_AVAILABLE = True
except ImportError:
    COLORAMA_AVAILABLE = False
    # Dummy colors if colorama not available
    class Fore:
        RESET = ''
        RED = ''
        YELLOW = ''
        GREEN = ''
        BLUE = ''
        MAGENTA = ''
        CYAN = ''
        WHITE = ''
    class Style:
        BRIGHT = ''
        DIM = ''
        RESET_ALL = ''

from config.settings import Settings


def _get_agent_color(name: str) -> str:
    """Get color for different agents."""
    if not COLORAMA_AVAILABLE:
        return ''
    
    name_lower = name.lower()
    
    # Image parsers
    if 'hero' in name_lower:
        return Fore.CYAN + Style.BRIGHT
    elif 'gallery' in name_lower:
        return Fore.BLUE + Style.BRIGHT
    elif 'aplus_product' in name_lower or 'product' in name_lower:
        return Fore.MAGENTA + Style.BRIGHT
    elif 'aplus_brand' in name_lower or 'brand' in name_lower:
        return Fore.GREEN + Style.BRIGHT
    elif 'aplus_manufacturer' in name_lower or 'manufacturer' in name_lower:
        return Fore.YELLOW + Style.BRIGHT
    # Other agents
    elif 'text' in name_lower:
        return Fore.WHITE + Style.BRIGHT
    elif 'review' in name_lower:
        return Fore.CYAN
    elif 'qa' in name_lower:
        return Fore.BLUE
    elif 'variant' in name_lower:
        return Fore.MAGENTA
    elif 'validator' in name_lower:
        return Fore.GREEN
    elif 'coordinator' in name_lower:
        return Fore.YELLOW + Style.BRIGHT
    elif 'browser' in name_lower:
        return Fore.WHITE
    elif 'database' in name_lower:
        return Fore.CYAN
    elif 'docx' in name_lower:
        return Fore.BLUE
    else:
        return ''


def _get_level_color(levelname: str) -> str:
    """Get color for different log levels."""
    if not COLORAMA_AVAILABLE:
        return ''
    
    level_colors = {
        'DEBUG': Fore.WHITE + Style.DIM,
        'INFO': Fore.WHITE,
        'WARNING': Fore.YELLOW + Style.BRIGHT,
        'ERROR': Fore.RED + Style.BRIGHT,
        'CRITICAL': Fore.RED + Back.WHITE + Style.BRIGHT,
    }
    return level_colors.get(levelname, '')


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors for console output."""
    
    def format(self, record):
        # Create a copy to avoid modifying the original record
        record_copy = logging.makeLogRecord(record.__dict__)
        
        # Get colors
        agent_color = _get_agent_color(record.name)
        level_color = _get_level_color(record.levelname)
        
        # Format message
        if COLORAMA_AVAILABLE:
            # Colorize level name
            record_copy.levelname = f"{level_color}{record.levelname}{Style.RESET_ALL}"
            
            # Colorize logger name (agent)
            record_copy.name = f"{agent_color}{record.name}{Style.RESET_ALL}"
            
            # Colorize message for WARNING and ERROR
            if record.levelno >= logging.WARNING:
                record_copy.msg = f"{level_color}{record.msg}{Style.RESET_ALL}"
        
        return super().format(record_copy)


def get_logger(name: str) -> logging.Logger:
    """
    Get a configured logger instance with colored output.
    
    Args:
        name: Logger name (usually __name__)
        
    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)
    
    if logger.handlers:
        return logger
    
    logger.setLevel(getattr(logging, Settings.LOG_LEVEL.upper(), logging.INFO))
    
    # Console handler with colors
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_format = ColoredFormatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(console_format)
    logger.addHandler(console_handler)
    
    # File handler
    logs_dir = Path('logs')
    logs_dir.mkdir(exist_ok=True)
    
    log_filename = logs_dir / f"parser_{datetime.now().strftime('%Y%m%d')}.log"
    file_handler = logging.FileHandler(log_filename, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(name)s | %(funcName)s:%(lineno)d | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_format)
    logger.addHandler(file_handler)
    
    logger.propagate = False
    
    return logger

