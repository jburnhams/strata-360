"""The local vision model on machines without MLX: Qwen3.5-9B through llama.cpp's `llama-server`.

The scenes, objects and regions scripts (scenes_vlm.py, objects_vlm.py, regions_vlm.py) run Qwen3.5-9B with mlx-vlm on a Mac. Anywhere else (a Windows or Linux PC with an NVIDIA GPU) they use this module instead: it starts `llama-server` with the
GGUF build of the same model (unsloth/Qwen3.5-9B-GGUF, Q4_K_M, 5.7 GB, and its vision projector), asks it one picture at a time with the same prompts and no thinking, and stops it again. On an RTX 5070 Ti it answers both scene prompts for a
picture in 1.2 s (the M4 Mac took 8.7 s) and agrees with the Mac's answers on 90 percent of settings and 97 percent of lens problems (docs/progress/2026-10-windows-gpu.md).

  STRATA_VLM_BACKEND=mlx|llama   force one (default: mlx when mlx_vlm is installed, else llama)
  STRATA_VLM_GGUF=FILE           the model file (its vision projector, mmproj-*.gguf, sits beside it); default models/qwen35-9b-gguf/Qwen3.5-9B-Q4_K_M.gguf, fetched on first use
  STRATA_LLAMA_SERVER=EXE        llama-server (default: on the PATH, or the winget package ggml.llamacpp)"""
import base64, contextlib, glob, importlib.util, json, os, shutil, socket, subprocess, sys, time, urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
REPO, WEIGHTS, PROJECTOR = 'unsloth/Qwen3.5-9B-GGUF', 'Qwen3.5-9B-Q4_K_M.gguf', 'mmproj-F16.gguf'


def use_llama():
    want = os.environ.get('STRATA_VLM_BACKEND')
    if want in ('mlx', 'llama'): return want == 'llama'
    return importlib.util.find_spec('mlx_vlm') is None


def vision_python():
    """The interpreter that runs the vision scripts: STRATA_VISION_PYTHON, else the `.venv-vision` of a Mac setup, else this one (the main environment has everything the llama.cpp path needs)."""
    from strata360 import oslib
    p = os.environ.get('STRATA_VISION_PYTHON') or oslib.venv_python(os.path.join(ROOT, '.venv-vision'))
    return p if os.path.exists(p) else sys.executable


def server_exe():
    for c in (os.environ.get('STRATA_LLAMA_SERVER'), shutil.which('llama-server'), *glob.glob(os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'WinGet', 'Packages', 'ggml.llamacpp_*', 'llama-server.exe'))):
        if c and os.path.exists(c): return c
    raise SystemExit('no llama-server: winget install ggml.llamacpp (or set STRATA_LLAMA_SERVER)')


def model_files():
    """(weights, projector) paths, fetched from Hugging Face on first use."""
    env = os.environ.get('STRATA_VLM_GGUF')
    if env: return env, (glob.glob(os.path.join(os.path.dirname(env), 'mmproj*.gguf')) or [None])[0]
    d = os.path.join(ROOT, 'models', 'qwen35-9b-gguf')
    if not (os.path.exists(os.path.join(d, WEIGHTS)) and os.path.exists(os.path.join(d, PROJECTOR))):
        from huggingface_hub import hf_hub_download
        for f in (WEIGHTS, PROJECTOR): hf_hub_download(REPO, f, local_dir=d)
    return os.path.join(d, WEIGHTS), os.path.join(d, PROJECTOR)


def llm_files():
    """(weights, projector) of the local TEXT model (vocabulary review, a local script writer, choosing shots): STRATA_LLM_GGUF, else Qwen3.6-35B-A3B (models/qwen36-35b-a3b, a mixture of experts with 3B active: fast and strong, 20 GB so partly in memory),
    else the Qwen3.5-9B of the picture model. The projector is only needed for pictures, so it is returned for the 35B and not used."""
    env = os.environ.get('STRATA_LLM_GGUF')
    if env: return env, None
    moe = os.path.join(ROOT, 'models', 'qwen36-35b-a3b', 'Qwen3.6-35B-A3B-Q4_K_M.gguf')
    if os.path.exists(moe): return moe, None
    return model_files()[0], None


def label(weights=None):
    """The model's name in the answers' records (the Mac's is "mlx-community/Qwen3.5-9B-4bit"), so a different build is never mistaken for it."""
    w = os.path.basename(weights or model_files()[0]); base = os.path.splitext(w)[0]; quant = base.rsplit('-', 1)[-1]
    return f'{REPO}:{quant}' if 'Qwen3.5-9B' in w else f'ggml-org/{base.rsplit("-", 1)[0]}-GGUF:{quant}'


class Server:
    """`with Server() as vlm: vlm.ask(prompt, image_path, max_tokens)`: llama-server started for the block."""
    def __init__(self, weights=None, projector=None, text=False):
        """`text`: a text-only model (no projector; `llm_files()` unless `weights` is given)."""
        w, p = llm_files() if text else model_files(); self.weights, self.projector = weights or w, (None if text and weights is None and p is None else projector or p); self.proc = None; self.port = None

    def __enter__(self):
        with socket.socket() as s: s.bind(('127.0.0.1', 0)); self.port = s.getsockname()[1]
        big = os.path.getsize(self.weights) > 12 * 2 ** 30                                                 # a model that does not fit the GPU whole (the 20 GB MoE): llama-server fits as much as it can and leaves the rest in memory
        cmd = [server_exe(), '-m', self.weights, *([] if big else ['-ngl', '99']), '-c', '8192', '--port', str(self.port), '--jinja', '--no-webui', '--parallel', '1'] + (['--mmproj', self.projector] if self.projector else [])
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); t0 = time.time()
        while True:
            if self.proc.poll() is not None: raise RuntimeError(f'llama-server stopped ({self.proc.returncode}): run it by hand to see why: {" ".join(cmd)}')
            try:
                if json.load(urllib.request.urlopen(f'http://127.0.0.1:{self.port}/health', timeout=2)).get('status') == 'ok': return self
            except Exception: pass
            if time.time() - t0 > 600: self.__exit__(); raise RuntimeError('llama-server did not become ready in 10 minutes')
            time.sleep(1)

    def __exit__(self, *exc):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            with contextlib.suppress(Exception): self.proc.wait(timeout=10)
            if self.proc.poll() is None: self.proc.kill()

    def ask(self, prompt, image, max_tokens=256, temperature=0.0):
        """The model's answer (text) to `prompt` about the picture file `image` (or several: a list, in order): no thinking, greedy, the same repetition penalty as the MLX run."""
        imgs = [image] if isinstance(image, (str, os.PathLike)) else list(image)
        parts = [dict(type='image_url', image_url=dict(url='data:image/jpeg;base64,' + base64.b64encode(open(f, 'rb').read()).decode())) for f in imgs]
        body = dict(model='qwen', temperature=temperature, max_tokens=max_tokens, chat_template_kwargs=dict(enable_thinking=False), messages=[dict(role='user', content=parts + [dict(type='text', text=prompt)])])
        if temperature == 0.0: body['repeat_penalty'] = 1.05
        else: body['top_p'] = 0.95
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/v1/chat/completions', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        return json.load(urllib.request.urlopen(req, timeout=600))['choices'][0]['message']['content']

    def chat(self, messages, max_tokens=1500, temperature=0.0, json_mode=False):
        """The answer text of a chat (a list of {role, content}); no thinking."""
        body = dict(model='qwen', temperature=temperature, top_p=0.95, max_tokens=max_tokens, chat_template_kwargs=dict(enable_thinking=False), messages=messages)
        if temperature == 0.0: body['repeat_penalty'] = 1.05
        req = urllib.request.Request(f'http://127.0.0.1:{self.port}/v1/chat/completions', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        return json.load(urllib.request.urlopen(req, timeout=1800))['choices'][0]['message']['content']
