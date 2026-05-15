"""
Media handler for downloading and processing images/videos.
Supports watermarking, compression, and format conversion.
"""

import os
import io
import hashlib
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timezone
import structlog

from PIL import Image, ImageDraw, ImageFont
import aiohttp

from config import settings

logger = structlog.get_logger(__name__)


class MediaHandler:
    """
    Handler for downloading and processing media files.
    """

    def __init__(self):
        self.media_path = Path(settings.media_path)
        self.media_path.mkdir(parents=True, exist_ok=True)
        self._font: Optional[ImageFont.FreeTypeFont] = None

    def _get_font(self, size: int = 24) -> ImageFont.FreeTypeFont:
        """Get or create font for watermark."""
        if self._font is None or self._font.size != size:
            try:
                # Try common font paths
                font_paths = [
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                    "/usr/share/fonts/TTF/DejaVuSans.ttf",
                    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
                    "/System/Library/Fonts/Helvetica.ttc",
                    "C:\\Windows\\Fonts\\arial.ttf",
                ]
                for font_path in font_paths:
                    if os.path.exists(font_path):
                        self._font = ImageFont.truetype(font_path, size)
                        break
                else:
                    # Fall back to default font
                    self._font = ImageFont.load_default()
            except Exception as e:
                logger.warning("Failed to load font, using default", error=str(e))
                self._font = ImageFont.load_default()
        return self._font

    def _generate_filename(self, content: bytes, extension: str = "jpg") -> str:
        """Generate unique filename based on content hash."""
        content_hash = hashlib.md5(content).hexdigest()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"{timestamp}_{content_hash}.{extension}"

    async def download_from_url(
        self,
        url: str,
        filename: Optional[str] = None
    ) -> Optional[Path]:
        """Download media from URL."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    if response.status == 200:
                        content = await response.read()
                        
                        if not filename:
                            # Determine extension from content type
                            content_type = response.headers.get('Content-Type', '')
                            ext = self._get_extension_from_mime(content_type)
                            filename = self._generate_filename(content, ext)
                        
                        file_path = self.media_path / filename
                        file_path.write_bytes(content)
                        
                        logger.info(
                            "Media downloaded",
                            url=url,
                            path=str(file_path),
                            size=len(content)
                        )
                        return file_path
                    else:
                        logger.warning(
                            "Failed to download media",
                            url=url,
                            status=response.status
                        )
                        return None
        except Exception as e:
            logger.error("Download failed", url=url, error=str(e))
            return None

    def _get_extension_from_mime(self, mime_type: str) -> str:
        """Get file extension from MIME type."""
        mime_map = {
            'image/jpeg': 'jpg',
            'image/png': 'png',
            'image/gif': 'gif',
            'image/webp': 'webp',
            'video/mp4': 'mp4',
            'video/quicktime': 'mov',
            'video/x-matroska': 'mkv',
        }
        return mime_map.get(mime_type.split(';')[0].strip(), 'jpg')

    def add_watermark(
        self,
        image_path: Path,
        watermark_text: str,
        output_path: Optional[Path] = None,
        position: str = "bottom_right",
        opacity: int = 128,
        font_size: int = 24
    ) -> Optional[Path]:
        """
        Add text watermark to image.
        
        Args:
            image_path: Path to input image
            watermark_text: Text to add as watermark
            output_path: Path for output image (default: overwrite input)
            position: Position of watermark (bottom_right, bottom_left, top_right, top_left, center)
            opacity: Opacity of watermark (0-255)
            font_size: Font size for watermark
        
        Returns:
            Path to watermarked image or None if failed
        """
        try:
            # Open image
            with Image.open(image_path) as img:
                # Convert to RGBA if necessary
                if img.mode != 'RGBA':
                    img = img.convert('RGBA')
                
                # Create transparent overlay
                overlay = Image.new('RGBA', img.size, (255, 255, 255, 0))
                draw = ImageDraw.Draw(overlay)
                
                # Get font
                font = self._get_font(font_size)
                
                # Get text bounding box
                bbox = draw.textbbox((0, 0), watermark_text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                
                # Calculate position
                padding = 10
                img_width, img_height = img.size
                
                positions = {
                    'bottom_right': (img_width - text_width - padding, img_height - text_height - padding),
                    'bottom_left': (padding, img_height - text_height - padding),
                    'top_right': (img_width - text_width - padding, padding),
                    'top_left': (padding, padding),
                    'center': ((img_width - text_width) // 2, (img_height - text_height) // 2),
                }
                
                x, y = positions.get(position, positions['bottom_right'])
                
                # Draw text with opacity
                draw.text((x, y), watermark_text, font=font, fill=(255, 255, 255, opacity))
                
                # Composite
                watermarked = Image.alpha_composite(img, overlay)
                
                # Determine output path
                if output_path is None:
                    output_path = image_path
                
                # Convert to RGB for JPEG saving
                if output_path.suffix.lower() in ['.jpg', '.jpeg']:
                    watermarked = watermarked.convert('RGB')
                
                # Save
                save_kwargs = {}
                if output_path.suffix.lower() in ['.jpg', '.jpeg']:
                    save_kwargs['quality'] = 90
                    save_kwargs['optimize'] = True
                elif output_path.suffix.lower() == '.png':
                    save_kwargs['optimize'] = True
                
                watermarked.save(output_path, **save_kwargs)
                
                logger.info(
                    "Watermark added",
                    input=str(image_path),
                    output=str(output_path),
                    text=watermark_text,
                    position=position
                )
                return output_path
                
        except Exception as e:
            logger.error("Failed to add watermark", path=str(image_path), error=str(e))
            return None

    def compress_image(
        self,
        image_path: Path,
        output_path: Optional[Path] = None,
        quality: int = 85,
        max_size: Tuple[int, int] = (1920, 1920)
    ) -> Optional[Path]:
        """
        Compress and resize image.
        
        Args:
            image_path: Path to input image
            output_path: Path for output image
            quality: JPEG quality (1-100)
            max_size: Maximum dimensions (width, height)
        
        Returns:
            Path to compressed image or None if failed
        """
        try:
            with Image.open(image_path) as img:
                # Resize if necessary
                img_width, img_height = img.size
                max_width, max_height = max_size
                
                if img_width > max_width or img_height > max_height:
                    # Calculate new size maintaining aspect ratio
                    ratio = min(max_width / img_width, max_height / img_height)
                    new_size = (int(img_width * ratio), int(img_height * ratio))
                    img = img.resize(new_size, Image.Resampling.LANCZOS)
                    logger.info("Image resized", original=(img_width, img_height), new=new_size)
                
                # Determine output path
                if output_path is None:
                    output_path = image_path
                
                # Convert to RGB if necessary
                if img.mode in ['RGBA', 'P']:
                    img = img.convert('RGB')
                
                # Save with compression
                save_kwargs = {
                    'quality': quality,
                    'optimize': True,
                    'progressive': True,
                }
                
                img.save(output_path, **save_kwargs)
                
                # Log compression ratio
                original_size = image_path.stat().st_size
                compressed_size = output_path.stat().st_size
                ratio = (1 - compressed_size / original_size) * 100 if original_size > 0 else 0
                
                logger.info(
                    "Image compressed",
                    input=str(image_path),
                    output=str(output_path),
                    original_size=original_size,
                    compressed_size=compressed_size,
                    reduction_percent=round(ratio, 1)
                )
                return output_path
                
        except Exception as e:
            logger.error("Failed to compress image", path=str(image_path), error=str(e))
            return None

    def process_media(
        self,
        image_path: Path,
        watermark_text: Optional[str] = None,
        compress: bool = True,
        quality: int = 85
    ) -> Optional[Path]:
        """
        Full media processing pipeline.
        
        Args:
            image_path: Path to input image
            watermark_text: Optional watermark text
            compress: Whether to compress the image
            quality: Compression quality
        
        Returns:
            Path to processed image or None if failed
        """
        try:
            result_path = image_path
            
            # Add watermark if specified
            if watermark_text:
                watermarked_path = self.add_watermark(result_path, watermark_text)
                if watermarked_path:
                    result_path = watermarked_path
                else:
                    logger.warning("Watermark failed, continuing without it")
            
            # Compress if requested
            if compress:
                compressed_path = self.compress_image(result_path, quality=quality)
                if compressed_path:
                    result_path = compressed_path
                else:
                    logger.warning("Compression failed, using previous version")
            
            return result_path
            
        except Exception as e:
            logger.error("Media processing failed", path=str(image_path), error=str(e))
            return None

    def get_media_type(self, file_path: Path) -> str:
        """Determine media type from file extension."""
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
        video_extensions = {'.mp4', '.mov', '.avi', '.mkv', '.webm'}
        
        suffix = file_path.suffix.lower()
        if suffix in image_extensions:
            return 'photo'
        elif suffix in video_extensions:
            return 'video'
        else:
            return 'document'

    def cleanup_old_media(self, max_age_days: int = 7) -> int:
        """
        Remove media files older than specified age.
        
        Returns:
            Number of files deleted
        """
        deleted_count = 0
        cutoff = datetime.now(timezone.utc).timestamp() - (max_age_days * 24 * 60 * 60)
        
        try:
            for file_path in self.media_path.iterdir():
                if file_path.is_file():
                    mtime = file_path.stat().st_mtime
                    if mtime < cutoff:
                        file_path.unlink()
                        deleted_count += 1
                        logger.debug("Deleted old media", path=str(file_path))
            
            logger.info("Media cleanup completed", deleted=deleted_count)
            return deleted_count
            
        except Exception as e:
            logger.error("Media cleanup failed", error=str(e))
            return 0
