from transformers import Qwen3VLForConditionalGeneration, AutoProcessor, Qwen3VLProcessor
from transformers import AutoModelForImageTextToText, AutoProcessor
from pydantic import BaseModel
from PIL import Image
from qwen_vl_utils import process_vision_info
import subprocess
import tempfile
import os
import platform
import shutil
from pathlib import Path
from typing import Tuple

def detect_image_format(image_path: str) -> str:
    """Detect image format from magic bytes.
    
    Args:
        image_path: Path to the image file
        
    Returns:
        Format string (e.g., 'PNG', 'JPEG', 'WMF', 'GIF', etc.)
    """
    with open(image_path, 'rb') as f:
        header = f.read(16)
    
    # Check magic bytes for common formats
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'PNG'
    elif header.startswith(b'\xff\xd8\xff'):
        return 'JPEG'
    elif header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):
        return 'GIF'
    elif header.startswith(b'RIFF') and b'WEBP' in header[:12]:
        return 'WEBP'
    elif header.startswith(b'BM'):
        return 'BMP'
    elif len(header) >= 4:
        # WMF magic bytes: 
        # - Placeable WMF: 0x9AC6CDD7 (little-endian: D7 CD C6 9A)
        # - Standard WMF: 0x0100 (little-endian: 00 01 00 00)
        # Check for placeable WMF first (more common in PowerPoint)
        if header[:4] == b'\xd7\xcd\xc6\x9a':
            return 'WMF'
        # Check for standard WMF (starts with 0x0100)
        elif len(header) >= 2 and header[:2] == b'\x01\x00':
            return 'WMF'
        # EMF files start with 0x00000001 (little-endian: 01 00 00 00)
        elif header[:4] == b'\x01\x00\x00\x00' and len(header) >= 8:
            # EMF has additional header info, but 0x00000001 is a strong indicator
            return 'EMF'
    
    # Try to detect from file extension as fallback
    ext = Path(image_path).suffix.lower()
    if ext == '.wmf':
        return 'WMF'
    elif ext == '.emf':
        return 'EMF'
    
    return 'UNKNOWN'


def check_libreoffice_available() -> Tuple[bool, str]:
    """Check if LibreOffice is available on the system.
    
    Returns:
        Tuple of (is_available, command_path)
        - is_available: True if LibreOffice is found
        - command_path: Path to libreoffice command or None
    """
    # Check for libreoffice command
    libreoffice_cmd = shutil.which('libreoffice')
    if libreoffice_cmd:
        return True, libreoffice_cmd
    
    # On macOS, LibreOffice might be in Applications
    system = platform.system().lower()
    if system == 'darwin':
        # Check common macOS locations
        possible_paths = [
            '/Applications/LibreOffice.app/Contents/MacOS/soffice',
            '/Applications/LibreOffice.app/Contents/MacOS/soffice.bin',
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return True, path
    
    return False, None


def convert_wmf_via_libreoffice(wmf_path: str, output_path: str) -> bool:
    """Convert WMF to PNG using LibreOffice directly.
    
    LibreOffice supports direct WMF→PNG conversion via headless mode.
    This bypasses ImageMagick entirely and avoids delegate issues.
    
    Args:
        wmf_path: Path to the WMF file
        output_path: Path for the output PNG file
        
    Returns:
        True if conversion succeeded, False otherwise
    """
    is_available, libreoffice_cmd = check_libreoffice_available()
    if not is_available:
        return False
    
    temp_dir = tempfile.mkdtemp()
    try:
        result = subprocess.run(
            [libreoffice_cmd, '--headless', '--convert-to', 'png', '--outdir', temp_dir, wmf_path],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            return False
        
        # LibreOffice creates PNG with same base name as input
        input_basename = Path(wmf_path).stem
        temp_png = Path(temp_dir) / f"{input_basename}.png"
        
        if temp_png.exists():
            shutil.copy2(temp_png, output_path)
            return True
        
    except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
        pass
    except Exception:
        pass
    finally:
        try:
            shutil.rmtree(temp_dir)
        except Exception:
            pass
    
    return False


def check_imagemagick_available() -> Tuple[bool, str]:
    """Check if ImageMagick is available on the system.
    
    Returns:
        Tuple of (is_available, command_name)
        - is_available: True if ImageMagick is found
        - command_name: 'convert', 'magick', or None
    """
    # Check for 'magick' command (ImageMagick 7+)
    if shutil.which('magick'):
        return True, 'magick'
    
    # Check for 'convert' command (ImageMagick 6)
    if shutil.which('convert'):
        # Verify it's actually ImageMagick and not something else
        try:
            result = subprocess.run(
                ['convert', '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if 'ImageMagick' in result.stdout or 'ImageMagick' in result.stderr:
                return True, 'convert'
        except (subprocess.TimeoutExpired, FileNotFoundError, subprocess.SubprocessError):
            pass
    
    return False, None


def get_imagemagick_install_instructions() -> str:
    """Get OS-specific installation instructions for ImageMagick.
    
    Returns:
        Installation instructions string
    """
    system = platform.system().lower()
    
    if system == 'darwin':  # macOS
        return (
            "To install ImageMagick on macOS, run:\n"
            "  brew install imagemagick\n"
            "If you don't have Homebrew, install it from https://brew.sh"
        )
    elif system == 'linux':
        # Try to detect the package manager
        if shutil.which('apt-get'):
            return (
                "To install ImageMagick on Linux (Debian/Ubuntu), run:\n"
                "  sudo apt-get update\n"
                "  sudo apt-get install imagemagick"
            )
        elif shutil.which('yum'):
            return (
                "To install ImageMagick on Linux (RHEL/CentOS), run:\n"
                "  sudo yum install ImageMagick"
            )
        elif shutil.which('dnf'):
            return (
                "To install ImageMagick on Linux (Fedora), run:\n"
                "  sudo dnf install ImageMagick"
            )
        else:
            return (
                "To install ImageMagick on Linux, use your system's package manager.\n"
                "Common commands:\n"
                "  - Debian/Ubuntu: sudo apt-get install imagemagick\n"
                "  - RHEL/CentOS: sudo yum install ImageMagick\n"
                "  - Fedora: sudo dnf install ImageMagick"
            )
    elif system == 'windows':
        return (
            "To install ImageMagick on Windows:\n"
            "1. Download the installer from https://imagemagick.org/script/download.php\n"
            "2. Run the installer and make sure to check 'Install legacy utilities (e.g. convert)'\n"
            "3. Restart your terminal/command prompt after installation"
        )
    else:
        return (
            "Please install ImageMagick from https://imagemagick.org/\n"
            "Consult the documentation for your operating system."
        )


def convert_wmf_to_png(wmf_path: str, output_path: str = None) -> str:
    """Convert WMF or EMF file to PNG using ImageMagick or other available tools.
    
    Args:
        wmf_path: Path to the WMF or EMF file
        output_path: Optional output path. If None, creates a temp file.
        
    Returns:
        Path to the converted PNG file
        
    Raises:
        RuntimeError: If conversion fails
    """
    if output_path is None:
        output_path = str(Path(wmf_path).with_suffix('.png'))
    
    # Check if ImageMagick is available
    is_available, command = check_imagemagick_available()
    
    if not is_available:
        install_instructions = get_imagemagick_install_instructions()
        raise RuntimeError(
            f"WMF/EMF file cannot be processed. ImageMagick is not installed or not found in PATH.\n\n"
            f"{install_instructions}\n\n"
            f"After installing, please restart your terminal and try again."
        )
    
    # Use the available ImageMagick command
    # Handle files with incorrect extensions by creating a temp file with correct extension
    temp_input_file = None
    try:
        # Detect the actual format from the file
        detected_format = detect_image_format(wmf_path)
        
        # If the file has the wrong extension, create a temp copy with correct extension
        input_file = wmf_path
        if detected_format == 'WMF' and not wmf_path.lower().endswith('.wmf'):
            # Create temporary file with .wmf extension
            temp_input_file = tempfile.NamedTemporaryFile(suffix='.wmf', delete=False)
            temp_input_file.close()
            # Copy the WMF data to the temp file
            with open(wmf_path, 'rb') as src, open(temp_input_file.name, 'wb') as dst:
                dst.write(src.read())
            input_file = temp_input_file.name
        elif detected_format == 'EMF' and not wmf_path.lower().endswith('.emf'):
            # Create temporary file with .emf extension
            temp_input_file = tempfile.NamedTemporaryFile(suffix='.emf', delete=False)
            temp_input_file.close()
            # Copy the EMF data to the temp file
            with open(wmf_path, 'rb') as src, open(temp_input_file.name, 'wb') as dst:
                dst.write(src.read())
            input_file = temp_input_file.name
        
        # Build ImageMagick command with explicit format specification
        # Try to bypass delegates that might fail (like LibreOffice)
        cmd_args = [command]
        
        # For ImageMagick 7 (magick command), we can specify format explicitly
        if command == 'magick':
            # Explicitly specify input format and output format
            if detected_format == 'WMF':
                cmd_args.extend(['wmf:', input_file, 'png:', output_path])
            elif detected_format == 'EMF':
                cmd_args.extend(['emf:', input_file, 'png:', output_path])
            else:
                cmd_args.extend([input_file, output_path])
        else:
            # For ImageMagick 6 (convert command)
            # Try to specify format explicitly using define
            if detected_format == 'WMF':
                cmd_args.extend(['-define', 'wmf:use-pixmap=1', input_file, output_path])
            elif detected_format == 'EMF':
                cmd_args.extend(['-define', 'emf:use-pixmap=1', input_file, output_path])
            else:
                cmd_args.extend([input_file, output_path])
        
        result = subprocess.run(
            cmd_args,
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
        else:
            # If the first attempt failed, try a different approach
            # Check if it's a delegate issue
            is_delegate_error = 'delegate' in result.stderr.lower() or 'libreoffice' in result.stderr.lower()
            
            if is_delegate_error:
                # Try to use ImageMagick without delegates by specifying format more explicitly
                # For ImageMagick 7, try using the format: prefix more explicitly
                if command == 'magick':
                    # Try with explicit format and additional options
                    cmd_args_retry = [command]
                    if detected_format == 'WMF':
                        # Try reading as WMF and forcing PNG output
                        cmd_args_retry.extend(['wmf:', input_file, '-background', 'white', '-alpha', 'remove', 'png:', output_path])
                    elif detected_format == 'EMF':
                        cmd_args_retry.extend(['emf:', input_file, '-background', 'white', '-alpha', 'remove', 'png:', output_path])
                    
                    result_retry = subprocess.run(
                        cmd_args_retry,
                        capture_output=True,
                        text=True,
                        timeout=30
                    )
                    if result_retry.returncode == 0 and os.path.exists(output_path):
                        return output_path
                
                # If still failing, try using LibreOffice directly as a fallback
                if detected_format == 'WMF':
                    try:
                        if convert_wmf_via_libreoffice(input_file, output_path):
                            return output_path
                    except Exception:
                        pass  # Fall through to error message
                
                # If LibreOffice direct conversion also failed, provide helpful error message
                is_libreoffice_available, libreoffice_cmd = check_libreoffice_available()
                system = platform.system().lower()
                
                if not is_libreoffice_available:
                    libreoffice_help = ""
                    if system == 'darwin':
                        libreoffice_help = (
                            "\n\nLibreOffice is not found in PATH. To fix this:\n"
                            "1. Install LibreOffice:\n"
                            "   brew install --cask libreoffice\n"
                            "2. Make sure LibreOffice command-line tools are in your PATH\n"
                            "   (You may need to restart your terminal after installation)\n"
                            "3. Or try rebuilding ImageMagick with native WMF support:\n"
                            "   brew reinstall imagemagick --with-wmf\n"
                        )
                    elif system == 'linux':
                        libreoffice_help = (
                            "\n\nLibreOffice is not found in PATH. To fix this:\n"
                            "  sudo apt-get install libreoffice  # Debian/Ubuntu\n"
                            "  sudo yum install libreoffice       # RHEL/CentOS\n"
                            "  sudo dnf install libreoffice       # Fedora\n"
                            "After installation, make sure 'libreoffice' command is in your PATH.\n"
                        )
                    else:
                        libreoffice_help = (
                            "\n\nLibreOffice is not found in PATH. Install it from:\n"
                            "  https://www.libreoffice.org/download/\n"
                            "Make sure the command-line tools are available in your PATH.\n"
                        )
                else:
                    # LibreOffice is installed but delegate is failing
                    libreoffice_help = (
                        f"\n\nLibreOffice is installed at: {libreoffice_cmd}\n"
                        f"But ImageMagick's delegate is not working properly.\n"
                        f"This might be a configuration issue with ImageMagick.\n"
                        f"Try:\n"
                        f"1. Restart your terminal\n"
                        f"2. Verify LibreOffice works: {libreoffice_cmd} --version\n"
                        f"3. Check ImageMagick delegate configuration\n"
                    )
                
                error_msg = result.stderr or result.stdout or "Unknown error"
                raise RuntimeError(
                    f"ImageMagick conversion failed due to LibreOffice delegate issue.\n"
                    f"ImageMagick on your system is configured to use LibreOffice for WMF/EMF conversion, "
                    f"but the delegate is not working properly.\n\n"
                    f"Error details: {error_msg}"
                    f"{libreoffice_help}"
                )
            
            # For non-delegate errors, provide the original error
            error_msg = result.stderr or result.stdout or "Unknown error"
            raise RuntimeError(
                f"ImageMagick conversion failed with exit code {result.returncode}.\n"
                f"Error: {error_msg}"
            )
    except subprocess.TimeoutExpired:
        raise RuntimeError("ImageMagick conversion timed out after 30 seconds.")
    except FileNotFoundError:
        install_instructions = get_imagemagick_install_instructions()
        raise RuntimeError(
            f"ImageMagick command '{command}' not found.\n\n"
            f"{install_instructions}"
        )
    except subprocess.SubprocessError as e:
        raise RuntimeError(f"ImageMagick conversion failed: {e}")
    finally:
        # Clean up temporary input file if created
        if temp_input_file and os.path.exists(temp_input_file.name):
            try:
                os.unlink(temp_input_file.name)
            except Exception:
                pass  # Ignore cleanup errors


class AltTextModel(BaseModel):
    """Singleton model for generating alt text for images."""
    processor: Qwen3VLProcessor | None = None
    model: Qwen3VLForConditionalGeneration | None = None
    
    class Config:
        arbitrary_types_allowed = True
    
    
    @classmethod
    def load(cls) -> "AltTextModel":
        """Initialize the model and processor."""
        model_name = "Qwen/Qwen3-VL-4B-Instruct"
        processor = AutoProcessor.from_pretrained(model_name)
        model = AutoModelForImageTextToText.from_pretrained(
            model_name,
            dtype="auto",
            device_map="auto",
            attn_implementation="eager"
        ).eval()
        return cls(processor=processor, model=model)
    
    def generate_alt_text(self, image_path: str) -> str:
        """Generate alt text for a given image.
        
        Args:
            image_path: Path to the image file
            
        Returns:
            Generated alt text as a string
        """
        temp_file_path = None
        try:
            if not self.model or not self.processor:
                raise ValueError("Model or processor not initialized")
            
            print(image_path)
            
            # Detect image format and handle WMF files
            image_format = detect_image_format(image_path)
            actual_image_path = image_path
            
            if image_format in ('WMF', 'EMF'):
                # Convert WMF/EMF to PNG
                try:
                    # Create a temporary PNG file
                    temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                    temp_file.close()
                    temp_file_path = temp_file.name
                    actual_image_path = convert_wmf_to_png(image_path, temp_file_path)
                except Exception as e:
                    raise RuntimeError(f"Failed to convert {image_format} file: {e}")
            
            # Load and preprocess the image
            try:
                image = Image.open(actual_image_path).convert('RGB')
            except Exception as e:
                error_str = str(e).lower()
                if 'wmf' in error_str or 'emf' in error_str or 'cannot find loader' in error_str:
                    # Try to convert if it's a WMF/EMF that wasn't detected
                    try:
                        if temp_file_path is None:
                            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                            temp_file.close()
                            temp_file_path = temp_file.name
                        actual_image_path = convert_wmf_to_png(image_path, temp_file_path)
                        image = Image.open(actual_image_path).convert('RGB')
                    except Exception as conv_error:
                        raise RuntimeError(f"Failed to process image: {conv_error}")
                else:
                    raise
            
            # Resize image if it's too large
            max_size = 1024
            if max(image.size) > max_size:
                ratio = max_size / max(image.size)
                new_size = tuple(int(dim * ratio) for dim in image.size)
                image = image.resize(new_size, Image.Resampling.LANCZOS)
            
            # Create messages for the model
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "image": str(actual_image_path)
                        },
                        {
                            "type": "text",
                            "text": "Please provide a detailed description of this image for accessibility purposes. Include visual details, spatial relationships, text if present, and context. Focus on elements that would be important for someone who cannot see the image. Do not miss any details. If the image contains table and code or text, explain both. Do not leave the sentence midway."
                        }
                    ]
                }
            ]
            
            # Prepare inputs for inference
            text = self.processor.apply_chat_template(
                messages,
                tokenize=False,
                add_generation_prompt=True
            )
            
            image_inputs, video_inputs = process_vision_info(messages, image_patch_size=16)
            
            inputs = self.processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt"
            )
            
            # Move inputs to the same device as the model
            inputs = inputs.to(self.model.device)
            
            # Generate response
            generated_ids = self.model.generate(
                **inputs,
                max_new_tokens=512,
                pad_token_id=self.processor.tokenizer.pad_token_id,
                eos_token_id=self.processor.tokenizer.eos_token_id
            )
            
            generated_ids_trimmed = [
                out_ids[len(in_ids):] for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
            ]
            
            result = self.processor.batch_decode(
                generated_ids_trimmed,
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False
            )[0].strip()
            
            return result
            
        except Exception as e:
            print(f"Error generating alt text: {e}")
            return ""
        finally:
            # Clean up temp file if created
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.unlink(temp_file_path)
                except Exception:
                    pass  # Ignore cleanup errors 