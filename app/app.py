import os
import requests
from pathlib import Path
import tempfile
from datetime import datetime
import streamlit as st

# Set environment variables before any other imports
os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ['PYTORCH_JIT'] = '0'
os.environ['PYTORCH_NO_CUDA_MEMORY_CACHING'] = '1'
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:512'
os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'

# Import Streamlit first and set page config immediately
import streamlit as st
st.set_page_config(
    page_title="Alt Text Generator",
    page_icon="📊",
    layout="centered"
)

# Backend API configuration
BACKEND_URL = "http://localhost:5001"

# Initialize session state
if 'processed_files' not in st.session_state:
    st.session_state.processed_files = []
if 'stats' not in st.session_state:
    st.session_state.stats = {}
if 'current_file' not in st.session_state:
    st.session_state.current_file = None
if 'processing_started' not in st.session_state:
    st.session_state.processing_started = False
if 'last_progress' not in st.session_state:
    st.session_state.last_progress = None

st.title("📊 PowerPoint Alt Text Generator")
st.markdown("""
This app helps you add alt text to images in your PowerPoint presentations.
Upload your PowerPoint files, and we'll automatically generate descriptive alt text for all images.
""")

# Debug information
debug_info = st.empty()

# Create a file uploader for multiple files
uploaded_files = st.file_uploader("Upload your PowerPoint files", type=['pptx'], accept_multiple_files=True)

# Reset button
if st.button("Reset Processing"):
    st.session_state.processed_files = []
    st.session_state.stats = {}
    st.session_state.current_file = None
    st.session_state.processing_started = False
    st.session_state.last_progress = None
    st.rerun()

# Debug information about current state
debug_info.text(f"Processing started: {st.session_state.processing_started}")
debug_info.text(f"Uploaded files: {len(uploaded_files) if uploaded_files else 0}")

if uploaded_files and not st.session_state.processing_started:
    debug_info.text("Starting processing...")
    
    # Mark processing as started
    st.session_state.processing_started = True
    
    # Create a temporary directory to store the uploaded files
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)
        processed_files = []
        all_stats = []
        
        # Create progress elements
        file_progress_bar = st.progress(0)
        file_status_text = st.empty()
        stats_container = st.empty()
        error_container = st.empty()
        debug_container = st.empty()
        
        # Process each file
        total_files = len(uploaded_files)
        debug_container.text(f"Total files to process: {total_files}")
        
        for file_idx, uploaded_file in enumerate(uploaded_files, 1):
            debug_container.text(f"Processing file {file_idx}: {uploaded_file.name}")
            
            if uploaded_file in st.session_state.processed_files:
                debug_container.text(f"Skipping already processed file: {uploaded_file.name}")
                continue
                
            try:
                # Update file progress
                file_progress = int((file_idx / total_files) * 100)
                file_progress_bar.progress(file_progress)
                file_status_text.text(f"Processing file {file_idx} of {total_files}: {uploaded_file.name}")
                
                # Send file to backend for processing
                files = {'file': (uploaded_file.name, uploaded_file.getvalue())}
                response = requests.post(f"{BACKEND_URL}/process", files=files)
                
                if response.status_code != 200:
                    error_container.error(f"Error processing {uploaded_file.name}: {response.json().get('error', 'Unknown error')}")
                    continue
                
                result = response.json()
                stats = result['stats']
                
                if stats:
                    processed_files.append(result['output_file'])
                    all_stats.append({
                        'filename': uploaded_file.name,
                        'stats': stats
                    })
                    st.session_state.processed_files.append(uploaded_file)
                    st.session_state.stats[uploaded_file.name] = stats
                    debug_container.text(f"Successfully processed {uploaded_file.name}")
                else:
                    error_container.error(f"Failed to process {uploaded_file.name}: No output generated")
                
            except Exception as e:
                error_container.error(f"Error processing {uploaded_file.name}: {str(e)}")
                continue
            
            # Clear error container if no errors
            error_container.empty()
        
        # Update progress to 100%
        file_progress_bar.progress(100)
        file_status_text.text("All files processed!")
        
        # Display statistics
        if all_stats:
            with stats_container.container():
                st.subheader("📊 Processing Statistics")
                
                # Overall statistics
                total_slides = sum(s['stats']['total_slides'] for s in all_stats)
                total_images = sum(s['stats']['total_images'] for s in all_stats)
                total_with_alt = sum(s['stats']['images_with_alt'] for s in all_stats)
                total_without_alt = sum(s['stats']['images_without_alt'] for s in all_stats)
                
                st.markdown("### Overall Statistics")
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("Total Files Processed", len(all_stats))
                    st.metric("Total Slides", total_slides)
                with col2:
                    st.metric("Total Images", total_images)
                    st.metric("Images with Alt Text", total_with_alt)
                
                # Per-file statistics
                st.markdown("### Per-File Statistics")
                for file_stats in all_stats:
                    with st.expander(f"📄 {file_stats['filename']}"):
                        stats = file_stats['stats']
                        col1, col2 = st.columns(2)
                        with col1:
                            st.metric("Total Slides", stats['total_slides'])
                            st.metric("Total Images", stats['total_images'])
                        with col2:
                            st.metric("Images with Alt Text", stats['images_with_alt'])
                            st.metric("Images without Alt Text", stats['images_without_alt'])
            
            # Create download buttons for each processed file
            st.markdown("### Download Processed Files")
            for file_stats in all_stats:
                output_file = f"processed_{file_stats['filename']}"
                download_url = f"{BACKEND_URL}/download/{output_file}"
                st.download_button(
                    label=f"Download {file_stats['filename']}",
                    data=requests.get(download_url).content,
                    file_name=output_file,
                    mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                    on_click="ignore"
                )
        else:
            st.error("No files were successfully processed. Please try again.")
        
        # Reset processing state
        st.session_state.processing_started = False
        st.session_state.last_progress = None