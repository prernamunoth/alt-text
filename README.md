# Alt Text Generator for PowerPoint

An AI-powered tool that automatically generates descriptive alt text for images in PowerPoint presentations, improving accessibility and compliance with accessibility standards.

## Features

- 🔍 **Automatic Detection**: Scans PowerPoint presentations for images without alt text
- 🤖 **AI-Powered Generation**: Uses Qwen3-VL-4B-Instruct vision-language model to generate detailed, descriptive alt text
- 📊 **Multiple Interfaces**:
  - Command-line interface (CLI) for batch processing
  - Web interface (Streamlit) for easy file upload and processing
  - REST API (Flask) for integration with other applications
- 📈 **Progress Tracking**: Real-time progress updates during processing
- 📝 **Detailed Statistics**: Reports on slides processed, images found, and alt text added
- 💾 **Safe Processing**: Creates updated copies of presentations without modifying originals

## Installation

### Prerequisites

- Python 3.9 or higher
- pip or conda package manager

### Setup

1. Clone the repository:
```bash
git clone <repository-url>
cd alt-text
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. (Optional) Install development dependencies:
```bash
pip install -r requirements-dev.txt -r requirements-extras.txt
```

## Usage

### Command-Line Interface

Process a PowerPoint file from the command line:

```bash
python -m alt_text.core <path-to-presentation.pptx>
```

With custom output path:

```bash
python -m alt_text.core <path-to-presentation.pptx> --output <output-path.pptx>
```

Example:
```bash
python -m alt_text.core presentation.pptx --output processed_presentation.pptx
```

### Web Interface

1. Start the backend API server:
```bash
python app/backend.py
```

2. In a separate terminal, start the Streamlit web interface:
```bash
streamlit run app/app.py
```

3. Open your browser and navigate to the URL shown in the terminal (typically `http://localhost:8501`)

4. Upload one or more PowerPoint files through the web interface

5. Download the processed files with generated alt text

### API Endpoints

The Flask backend provides the following endpoints:

- **POST `/process`**: Process a PowerPoint file
  - Request: Multipart form data with `file` field
  - Response: JSON with processing statistics and output filename

- **GET `/download/<filename>`**: Download a processed file
  - Response: File download

- **GET `/status`**: Check API status
  - Response: JSON with status information

Example API usage:
```bash
curl -X POST -F "file=@presentation.pptx" http://localhost:5001/process
```

## How It Works

1. **Image Extraction**: The tool scans all slides in the PowerPoint presentation and identifies images
2. **Alt Text Detection**: For each image, it checks if alt text already exists
3. **AI Generation**: For images without alt text, the Qwen3-VL-4B-Instruct model generates detailed descriptions
4. **Alt Text Assignment**: Generated descriptions are added as alt text to the images
5. **File Saving**: The updated presentation is saved with a new filename

## Project Structure

```
alt-text/
├── alt_text/              # Core package
│   ├── __init__.py
│   ├── core.py           # Main CLI logic and PowerPoint processing
│   └── model.py          # AI model wrapper for alt text generation
├── app/                   # Application interfaces
│   ├── app.py            # Streamlit web interface
│   ├── backend.py        # Flask REST API
│   └── processor.py      # Processing wrapper
├── images/                # Extracted images (created during processing)
├── processed/             # Processed PowerPoint files
├── uploads/               # Uploaded files (web interface)
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## Requirements

Key dependencies include:
- `transformers` - Hugging Face transformers library
- `torch` - PyTorch for model inference
- `python-pptx` - PowerPoint file manipulation
- `streamlit` - Web interface
- `flask` - REST API backend
- `qwen-vl-utils` - Utilities for Qwen vision-language models
- `pillow` - Image processing

See `requirements.txt` for the complete list.

## Model Information

This project uses the **Qwen3-VL-4B-Instruct** model, a vision-language model capable of understanding images and generating detailed descriptions. The model is automatically downloaded from Hugging Face on first use.

## Limitations

- Only supports `.pptx` format (not older `.ppt` format)
- Requires sufficient system memory to load the AI model
- Processing time depends on the number of images and system performance
- Generated alt text quality depends on image clarity and content

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

BSD 3-Clause License

## Support

For issues, questions, or contributions, please open an issue on the project repository.
