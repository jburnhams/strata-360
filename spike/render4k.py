"""Compatibility shim: this module now lives in the strata360 package (strata360.render.flat). Kept so the early experiment scripts still run."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src'))
import importlib as _il
_m = _il.import_module("strata360.render.flat")
globals().update({k: v for k, v in vars(_m).items() if not k.startswith('__')})
if __name__ == '__main__' and hasattr(_m, 'main'):
    _m.main()
