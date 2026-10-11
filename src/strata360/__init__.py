import os, sys

if sys.platform == 'win32':                                      # Hugging Face's cache wants symlinks, which an ordinary Windows user may not create. It falls back to copies, but its parallel downloads race on the first test of that and one of them fails (OSError 1314):
    os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')    # so the test is made once, here, before anything downloads
    try:
        from huggingface_hub.file_download import are_symlinks_supported; are_symlinks_supported()
    except Exception: pass
