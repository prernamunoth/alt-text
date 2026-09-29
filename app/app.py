import os
import sys
import hashlib
from pathlib import Path
import tempfile
from threading import Lock

import streamlit as st

os.environ['CUDA_VISIBLE_DEVICES'] = ''
os.environ['PYTORCH_JIT'] = '0'
os.environ['PYTORCH_NO_CUDA_MEMORY_CACHING'] = '1'
os.environ['PYTORCH_ENABLE_MPS_FALLBACK'] = '1'

# Make the source package importable when Cloud runs app/app.py directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

st.set_page_config(page_title="Alt Text Generator", page_icon="📊", layout="centered")


@st.cache_resource(show_spinner=False)
def processing_resources():
    from alt_text.model import AltTextModel
    # The cached model is shared across sessions; serialize inference.
    return AltTextModel.load(), Lock()


def process_upload(uploaded_file, fast_mode, force_reprocess, progress_callback):
    from alt_text import check_alt_text

    model, lock = processing_resources()
    with tempfile.TemporaryDirectory() as directory:
        input_path = Path(directory) / "presentation.pptx"
        input_path.write_bytes(uploaded_file.getvalue())
        with lock:
            stats = check_alt_text(
                input_path,
                model=model,
                fast_mode=fast_mode,
                force_reprocess=force_reprocess,
                progress_callback=progress_callback,
                images_dir=Path(directory) / "images",
            )
        if not stats:
            raise RuntimeError("Unable to process this presentation. Check the app logs for details.")
        output_path = stats.get('output_path')
        # Read before cleanup; keep downloads available on subsequent reruns.
        data = Path(output_path).read_bytes() if output_path else input_path.read_bytes()
        return {'filename': uploaded_file.name, 'stats': stats, 'data': data}


if 'results' not in st.session_state:
    st.session_state.results = {}

st.title("📊 PowerPoint Alt Text Generator")
st.write("Upload PowerPoint presentations to generate descriptive alt text for their images.")
uploaded_files = st.file_uploader("Upload your PowerPoint files", type=['pptx'], accept_multiple_files=True)
fast_mode = st.checkbox("Fast Mode", value=True,
                        help="Skips slide title generation and diagram alt text to process large decks faster.")
force_reprocess = st.checkbox("Force Reprocess", value=False,
                              help="Rewrites existing alt text instead of keeping existing descriptions.")

if st.button("Reset Processing"):
    st.session_state.results = {}
    st.rerun()

if st.button("Start Processing", disabled=not uploaded_files):
    progress = st.progress(0)
    status = st.empty()
    succeeded = 0
    for index, uploaded_file in enumerate(uploaded_files):
        key = hashlib.sha256(uploaded_file.getvalue()).hexdigest()
        key = f"{uploaded_file.name}:{key}:{fast_mode}:{force_reprocess}"
        status.text(f"Processing file {index + 1} of {len(uploaded_files)}: {uploaded_file.name}")
        try:
            if key not in st.session_state.results or force_reprocess:
                with st.spinner("Loading the AI model and processing. The first run may take several minutes."):
                    def update_progress(current, total):
                        progress.progress(min((index + current / max(total, 1)) / len(uploaded_files), 1.0))

                    st.session_state.results[key] = process_upload(
                        uploaded_file, fast_mode, force_reprocess, update_progress
                    )
            succeeded += 1
        except Exception as exc:
            st.error(f"Error processing {uploaded_file.name}: {exc}")
        progress.progress((index + 1) / len(uploaded_files))
    status.text(f"Processing finished: {succeeded} of {len(uploaded_files)} file(s) successfully processed.")

if st.session_state.results:
    st.subheader("📊 Processing Statistics")
    results = list(st.session_state.results.values())
    left, right = st.columns(2)
    left.metric("Total Files Processed", len(results))
    left.metric("Total Slides", sum(item['stats']['total_slides'] for item in results))
    right.metric("Total Images", sum(item['stats']['total_images'] for item in results))
    right.metric("Images with Alt Text", sum(item['stats']['images_with_alt'] for item in results))
    for key, result in st.session_state.results.items():
        with st.expander(result['filename']):
            stats = result['stats']
            st.write(f"Slides: {stats['total_slides']} · Images: {stats['total_images']} · "
                     f"Images without alt text: {stats['images_without_alt']}")
            if not stats.get('modified'):
                st.info("No changes were needed. You can download the original presentation below.")
            st.download_button(
                f"Download {result['filename']}",
                data=result['data'],
                file_name=f"processed_{Path(result['filename']).name}",
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
                key=f"download:{key}",
            )
