
from pathlib import Path
from typing import Callable, Dict, Union

# Set PyTorch environment variables
# os.environ['CUDA_VISIBLE_DEVICES'] = ''
# os.environ['PYTORCH_JIT'] = '0'
# os.environ['PYTORCH_NO_CUDA_MEMORY_CACHING'] = '1'
# os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:512'

# Import PyTorch and related modules
from alt_text import check_alt_text

def process_presentation(pptx_path: Union[str, Path], progress_callback: Callable[[int, int], None] = None) -> Dict:
    """
    Process a PowerPoint presentation to add alt text to images.
    
    Args:
        pptx_path: Path to the PowerPoint file
        progress_callback: Optional callback function for progress updates
        
    Returns:
        Dictionary containing processing statistics
    """
    try:
        return check_alt_text(pptx_path, progress_callback=progress_callback)
    except Exception as e:
        raise Exception(f"Error processing presentation: {str(e)}") 