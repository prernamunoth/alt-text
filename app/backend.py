import os
from pathlib import Path
from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
import shutil

# Set environment variables before any other imports
os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ['PYTORCH_JIT'] = '0'
os.environ['PYTORCH_NO_CUDA_MEMORY_CACHING'] = '1'
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:512'
os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'

# Import alt_text after environment setup
from alt_text import check_alt_text
from alt_text.model import AltTextModel

# Initialize the model at startup
print("Initializing model...")
global_model = AltTextModel.load()

app = Flask(__name__)

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'processed'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)


print("Model initialized successfully")

@app.route('/process', methods=['POST'])
def process_presentation():
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        
        if not file.filename.endswith('.pptx'):
            return jsonify({'error': 'File must be a PowerPoint presentation (.pptx)'}), 400
        
        # Save the uploaded file
        filename = secure_filename(file.filename)
        input_path = Path(UPLOAD_FOLDER) / filename
        file.save(str(input_path))
        
        # Process the file
        def progress_callback(current, total):
            # This is a placeholder - in a real implementation, you might want to
            # use WebSocket or Server-Sent Events to send progress updates
            pass
        
        # Use the global model instance
        stats = check_alt_text(input_path, model=global_model, progress_callback=progress_callback)
        
        if not stats or not stats.get('output_path'):
            return jsonify({'error': 'Failed to process presentation'}), 500
        
        # Move the processed file to the output folder
        output_filename = f"processed_{filename}"
        output_path = Path(OUTPUT_FOLDER) / output_filename
        shutil.move(stats['output_path'], output_path)
        
        # Clean up the input file
        os.remove(input_path)
        
        return jsonify({
            'message': 'Processing complete',
            'stats': stats,
            'output_file': output_filename
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>', methods=['GET'])
def download_file(filename):
    try:
        file_path = Path(OUTPUT_FOLDER) / secure_filename(filename)
        if not file_path.exists():
            return jsonify({'error': 'File not found'}), 404
        
        return send_file(
            str(file_path),
            as_attachment=True,
            download_name=filename
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/status', methods=['GET'])
def status():
    return jsonify({
        'status': 'running',
        'upload_folder': len(os.listdir(UPLOAD_FOLDER)),
        'output_folder': len(os.listdir(OUTPUT_FOLDER))
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=False) 