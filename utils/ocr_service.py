"""OCR Service - OpenAI Vision API integration for image text recognition and visual description"""
import base64
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from PIL import Image
import io

try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

from utils.logger import get_logger
from config.settings import Settings

logger = get_logger(__name__)


class OCRService:
    """Service for OCR and visual description using OpenAI Vision API."""
    
    def __init__(self, api_key: str, model: str = None, max_retries: int = None, timeout: int = None):
        """
        Initialize OCR service.
        
        Args:
            api_key: OpenAI API key
            model: Model to use (default: gpt-4o-mini)
            max_retries: Maximum retries for API calls (default: 3)
            timeout: Timeout for API calls in seconds (default: 60)
        """
        if not OPENAI_AVAILABLE:
            raise ImportError("openai library is not installed. Install it with: pip install openai")
        
        if not api_key or not api_key.strip():
            raise ValueError("OpenAI API key is required")
        
        self.client = OpenAI(api_key=api_key.strip())
        self.model = model or getattr(Settings, 'OPENAI_MODEL', 'gpt-4o-mini')
        self.max_retries = max_retries or getattr(Settings, 'OPENAI_MAX_RETRIES', 3)
        self.timeout = timeout or getattr(Settings, 'OPENAI_TIMEOUT', 60)
        self._rate_limit_hit = False  # Track rate limit status
        
        logger.info(f"OCR Service initialized with model: {self.model}")
    
    def _encode_image_to_base64(self, image_path: Path) -> Optional[str]:
        """
        Encode image to base64 string.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Base64 encoded string or None if error
        """
        try:
            # Open and verify image
            img = Image.open(image_path)
            
            # Convert to RGB if needed (for JPEG compatibility)
            if img.mode in ('RGBA', 'LA', 'P'):
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                img = rgb_img
            
            # Resize if too large - optimize for token usage (1024x1024 max)
            # If image is smaller, keep original size
            max_size = 1024
            if img.width > max_size or img.height > max_size:
                # Maintain aspect ratio
                img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            
            # Convert to base64
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=95)
            image_bytes = buffer.getvalue()
            base64_string = base64.b64encode(image_bytes).decode('utf-8')
            
            return base64_string
            
        except Exception as e:
            logger.error(f"Failed to encode image {image_path}: {e}")
            return None
    
    def _create_prompt(self) -> str:
        """Create prompt for OpenAI Vision API (optimized for token usage)."""
        return """Extract two blocks:

1. OCR TEXT:
- All marketing text exactly as written (letter by letter). Preserve original formatting and line breaks if present.
- DO NOT translate or fix grammar
- SKIP: certificates, medical reports, review screenshots, packaging small text (manufacturer/address/QR), magazine text, unreadable text
- If no text: "No marketing text"

2. VISUAL:
3-6 points:
- Main object (people/product/packaging/ingredients, etc.)
- Placement (left/right/center)
- Style (clean/lifestyle/medical/cosmetic/natural/premium)
- Background/interior/objects
- Notable details (Before/After, icons, colors)

Rules: Only visible, no assumptions, no judgments, no fabrication, no unnecessary descriptions.

Format:
OCR TEXT:
[text or "No marketing text"]

VISUAL:
- [point 1]
- [point 2]
- [point 3]"""
    
    def _parse_response(self, response_text: str) -> Tuple[str, str]:
        """
        Parse OpenAI response into OCR text and Visual description.
        
        Args:
            response_text: Raw response from OpenAI
            
        Returns:
            Tuple of (ocr_text, visual_description)
        """
        ocr_text = ""
        visual_description = ""
        
        try:
            # Split by "VISUAL:" marker
            if "VISUAL:" in response_text:
                parts = response_text.split("VISUAL:", 1)
                ocr_section = parts[0].strip()
                visual_section = parts[1].strip()
                
                # Extract OCR text (remove "OCR TEXT:" prefix if present)
                if "OCR TEXT:" in ocr_section:
                    ocr_text = ocr_section.split("OCR TEXT:", 1)[1].strip()
                else:
                    ocr_text = ocr_section.strip()
                
                # Extract visual description (remove leading dashes if present, keep structure)
                visual_description = visual_section.strip()
            else:
                # Try to find OCR TEXT section
                if "OCR TEXT:" in response_text:
                    ocr_text = response_text.split("OCR TEXT:", 1)[1].strip()
                    # Try to find visual in remaining text
                    if "\n" in ocr_text:
                        lines = ocr_text.split("\n")
                        # Assume first part is OCR, rest might be visual
                        ocr_text = lines[0].strip()
                        visual_description = "\n".join(lines[1:]).strip()
                else:
                    # Fallback: use entire response as OCR
                    ocr_text = response_text.strip()
            
            # Clean up OCR text
            if not ocr_text or ocr_text.lower() in ["немає маркетингового тексту", "no marketing text", "no text"]:
                ocr_text = "Немає маркетингового тексту"
            
            # Clean up visual description
            if visual_description:
                # Remove "VISUAL:" if still present
                visual_description = visual_description.replace("VISUAL:", "").strip()
                # Ensure it starts with dashes for bullet points
                if visual_description and not visual_description.startswith("-"):
                    lines = visual_description.split("\n")
                    visual_description = "\n".join([f"- {line.strip()}" if line.strip() and not line.strip().startswith("-") else line.strip() for line in lines])
            
        except Exception as e:
            logger.warning(f"Failed to parse OCR response: {e}. Using raw response.")
            ocr_text = response_text.strip()
            visual_description = ""
        
        return ocr_text, visual_description
    
    def process_single_image(self, image_path: Path) -> Optional[Dict[str, str]]:
        """
        Process a single image through OpenAI Vision API.
        
        Args:
            image_path: Path to image file
            
        Returns:
            Dictionary with 'ocr_text' and 'visual' keys, or None if error
        """
        if not image_path.exists():
            logger.error(f"Image not found: {image_path}")
            return None
        
        # Encode image
        base64_image = self._encode_image_to_base64(image_path)
        if not base64_image:
            return None
        
        # Create prompt
        prompt = self._create_prompt()
        
        # Call OpenAI API with retries
        for attempt in range(self.max_retries):
            try:
                logger.debug(f"Processing image {image_path.name} (attempt {attempt + 1}/{self.max_retries})...")
                
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{base64_image}"
                                    }
                                }
                            ]
                        }
                    ],
                    max_tokens=1500,
                    timeout=self.timeout
                )
                
                response_text = response.choices[0].message.content
                ocr_text, visual_description = self._parse_response(response_text)
                
                # Extract token usage from response
                usage = response.usage if hasattr(response, 'usage') else None
                tokens_used = {
                    'prompt_tokens': usage.prompt_tokens if usage and hasattr(usage, 'prompt_tokens') else 0,
                    'completion_tokens': usage.completion_tokens if usage and hasattr(usage, 'completion_tokens') else 0,
                    'total_tokens': usage.total_tokens if usage and hasattr(usage, 'total_tokens') else 0,
                }
                
                logger.debug(f"✓ Processed image {image_path.name} ({tokens_used['total_tokens']} tokens)")
                
                return {
                    'ocr_text': ocr_text,
                    'visual': visual_description,
                    'tokens': tokens_used
                }
                
            except Exception as e:
                error_msg = str(e)
                wait_time = None
                
                # Check for rate limit error (429)
                if "429" in error_msg or "rate_limit" in error_msg.lower() or "rate limit" in error_msg.lower():
                    # Try to extract wait time from error message
                    import re
                    # Look for patterns like "try again in 403ms" or "try again in 1.5s" or "Please try again in 403ms"
                    wait_match = re.search(r'(?:try again|Please try again) in ([\d.]+)\s*(ms|s|seconds?|second)', error_msg, re.IGNORECASE)
                    if wait_match:
                        wait_value = float(wait_match.group(1))
                        wait_unit = wait_match.group(2).lower()
                        if 'ms' in wait_unit:
                            # Convert ms to seconds, add significant buffer (at least 2 seconds)
                            wait_time = max((wait_value / 1000) + 2.0, 3.0)
                        else:
                            # Add buffer for seconds (at least 2 seconds)
                            wait_time = max(wait_value + 2.0, 3.0)
                    else:
                        # Default wait time for rate limit (longer to be safe)
                        wait_time = 10.0
                    
                    logger.warning(f"Rate limit hit for {image_path.name}, waiting {wait_time:.1f}s...")
                    # Mark that we hit rate limit (for batch processing)
                    self._rate_limit_hit = True
                else:
                    # For other errors, use exponential backoff
                    wait_time = 2 ** attempt
                    logger.warning(f"Attempt {attempt + 1}/{self.max_retries} failed for {image_path.name}: {error_msg[:100]}")
                
                if attempt < self.max_retries - 1 and wait_time:
                    time.sleep(wait_time)
                elif attempt >= self.max_retries - 1:
                    logger.error(f"Failed to process {image_path.name} after {self.max_retries} attempts: {error_msg[:200]}")
                    return None
        
        return None
    
    def process_image_batch(self, image_paths: List[Path], batch_size: int = 5) -> Dict[str, Dict[str, str]]:
        """
        Process multiple images in batches.
        
        Args:
            image_paths: List of image file paths
            batch_size: Number of images to process in one API call (default: 5)
            
        Returns:
            Dictionary mapping image paths (as strings) to OCR results
        """
        results = {}
        start_time = time.time()
        failed_images = []
        
        if not image_paths:
            return results
        
        logger.info(f"Processing {len(image_paths)} images in batches of {batch_size}...")
        
        # Process in batches
        for i in range(0, len(image_paths), batch_size):
            batch = image_paths[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            total_batches = (len(image_paths) + batch_size - 1) // batch_size
            
            logger.info(f"Batch {batch_num}/{total_batches} ({len(batch)} images)...")
            
            # Reset rate limit flag for this batch
            self._rate_limit_hit = False
            
            # Process each image in batch (OpenAI Vision API processes one image per request)
            for img_path in batch:
                result = self.process_single_image(img_path)
                if result:
                    # Store result using relative path as key
                    results[str(img_path)] = result
                else:
                    failed_images.append(img_path.name)
            
            # Delay between batches - longer if rate limit was hit
            if i + batch_size < len(image_paths):
                if self._rate_limit_hit:
                    # Longer delay after rate limit (wait for rate limit window to reset)
                    delay = 15.0  # Increased delay to allow rate limit window to reset
                    logger.info(f"Rate limit detected, waiting {delay}s before next batch...")
                    time.sleep(delay)
                else:
                    time.sleep(2)  # Slightly longer default delay to avoid hitting limits
        
        elapsed_time = time.time() - start_time
        success_count = len(results)
        total_count = len(image_paths)
        
        # Calculate total tokens used
        total_tokens = {
            'prompt_tokens': 0,
            'completion_tokens': 0,
            'total_tokens': 0
        }
        for result in results.values():
            if 'tokens' in result:
                total_tokens['prompt_tokens'] += result['tokens'].get('prompt_tokens', 0)
                total_tokens['completion_tokens'] += result['tokens'].get('completion_tokens', 0)
                total_tokens['total_tokens'] += result['tokens'].get('total_tokens', 0)
        
        # Retry failed images individually with longer delays
        if failed_images:
            logger.warning(f"Retrying {len(failed_images)} failed images individually...")
            retry_failed = []
            for img_path in image_paths:
                if str(img_path) not in results:
                    retry_failed.append(img_path)
            
            # Retry each failed image with exponential backoff
            for img_path in retry_failed:
                logger.info(f"Retrying {img_path.name}...")
                for retry_attempt in range(3):  # 3 additional retries
                    result = self.process_single_image(img_path)
                    if result:
                        results[str(img_path)] = result
                        # Update token counts
                        if 'tokens' in result:
                            total_tokens['prompt_tokens'] += result['tokens'].get('prompt_tokens', 0)
                            total_tokens['completion_tokens'] += result['tokens'].get('completion_tokens', 0)
                            total_tokens['total_tokens'] += result['tokens'].get('total_tokens', 0)
                        break
                    else:
                        if retry_attempt < 2:  # Wait before next retry (except last attempt)
                            wait_time = 5 * (retry_attempt + 1)  # 5s, 10s, 15s
                            logger.debug(f"Retry {retry_attempt + 1}/3 failed, waiting {wait_time}s...")
                            time.sleep(wait_time)
            
            # Update counts after retries
            success_count = len(results)
            final_failed = [img_path.name for img_path in retry_failed if str(img_path) not in results]
            if final_failed:
                logger.error(f"Still failed after retries: {', '.join(final_failed[:5])}{'...' if len(final_failed) > 5 else ''}")
            else:
                logger.info("✓ All images processed successfully after retries")
        
        elapsed_time = time.time() - start_time
        logger.info(f"✓ OCR complete: {success_count}/{total_count} images ({elapsed_time:.1f}s, {total_tokens['total_tokens']} tokens)")
        
        # Store token usage in results metadata
        results['_metadata'] = {
            'total_tokens': total_tokens,
            'elapsed_time': elapsed_time,
            'success_count': success_count,
            'failed_count': total_count - success_count
        }
        
        return results

