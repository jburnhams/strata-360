import os, sys

if sys.platform == 'win32':                                      # Hugging Face's cache wants symlinks, which an ordinary Windows user may not create. It falls back to copies, but its parallel downloads race on the first test of that and one of them fails (OSError 1314):
    os.environ.setdefault('HF_HUB_DISABLE_SYMLINKS_WARNING', '1')    # so the test is made once, here, before anything downloads
    try:
        from huggingface_hub.file_download import are_symlinks_supported; are_symlinks_supported()
    except Exception: pass


# AMD GPUs on Linux: ROCm ships kernels for gfx1100 but not for gfx1101-1103 (a Ryzen 7840HS's Radeon 780M is gfx1103); there every kernel fails with 'invalid device function' until the chip is presented as gfx1100.
# The chip reports itself in /sys/class/kfd. This runs before any submodule imports torch (the ROCm runtime reads the variable at start); a value the user set wins. Same table in strata-stills (gpu.py).
AMD_OVERRIDE = {110001: '11.0.0', 110002: '11.0.0', 110003: '11.0.0'}


def amd_env(root='/sys/class/kfd/kfd/topology/nodes'):
    """{'HSA_OVERRIDE_GFX_VERSION': ...} when an AMD GPU here needs it and the user has not set it, else {}."""
    if 'HSA_OVERRIDE_GFX_VERSION' in os.environ: return {}
    import glob
    for f in sorted(glob.glob(os.path.join(root, '*', 'properties'))):
        try: props = dict(l.split(None, 1) for l in open(f).read().splitlines() if ' ' in l)
        except OSError: continue
        v = int(props.get('gfx_target_version', '0').strip() or 0)
        if props.get('vendor_id', '').strip() == '4098' and v in AMD_OVERRIDE: return {'HSA_OVERRIDE_GFX_VERSION': AMD_OVERRIDE[v]}
    return {}


os.environ.update(amd_env())
