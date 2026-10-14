import sys, json, os; sys.path.insert(0,'C:/Code/strata-360/src')
import numpy as np, cv2
from strata360 import oslib; oslib.lower_priority()
from strata360.pipeline import clips
from strata360.render import flat as r4
from strata360.osv.telemetry import read_frames
W,H=640,360; PHIS=np.arange(0,360,30)
MAN=json.load(open('corpus/manifest.json'))
CL={c.id:c for c in clips.discover("D:/Insta360/2024-07-20 - Crossing Switzerland")[0]}
_R={}
def renderer():
    if 'r' not in _R: _R['r']=r4.Renderer(next(iter(CL.values())).osv,W,H,100.0,'linear',grid=2)
    return _R['r']
def load(name,tag,i):
    g=cv2.imread(f'corpus/{name}_{tag}_{i}.jpg',cv2.IMREAD_GRAYSCALE); return cv2.resize(g,(3840,3840),interpolation=cv2.INTER_CUBIC)
_Q={}
def up_body(s):
    R=renderer()
    if s['clip'] not in _Q: _Q[s['clip']]=read_frames(CL[s['clip']].osv)['quat']
    return R.stab_matrix(_Q[s['clip']][s['k']])@np.array([0,0,1.0])
def ring_scores(s,rear_i=2,front_i=2,warp=False):
    """disagreement (relative mean abs diff of the two lenses' own pictures) in each ring direction, both lenses seeing the ray (theta < 92)"""
    R=renderer(); gs=load(s['name'],'rear',rear_i); gm=load(s['name'],'front',front_i); up=up_body(s); out=[]
    for phi in PHIS:
        a=np.radians(phi); f=np.array([np.cos(a),0,np.sin(a)])
        (um,vm,tm),(us,vs,ts)=R.maps(f,up)
        A=cv2.remap(gm,um.astype(np.float32),vm.astype(np.float32),cv2.INTER_LINEAR).astype(np.float32); B=cv2.remap(gs,us.astype(np.float32),vs.astype(np.float32),cv2.INTER_LINEAR).astype(np.float32)
        A=cv2.GaussianBlur(A,(0,0),1.0)-cv2.GaussianBlur(A,(0,0),6.0); B=cv2.GaussianBlur(B,(0,0),1.0)-cv2.GaussianBlur(B,(0,0),6.0)      # edges only: glare and exposure differences between the lenses drop out
        ov=(tm<98)&(ts<98); m=ov&(cv2.erode(ov.astype(np.uint8),np.ones((9,9)))>0)
        if m.sum()<200: out.append(np.nan); continue
        a_,b_=A[m],B[m]; d=np.sqrt((a_*a_).mean()*(b_*b_).mean())
        out.append(float(1-(a_*b_).mean()/d) if d>1e-3 else np.nan)       # 0 = edges coincide, 1 = unrelated
    return np.array(out)
def evaluate(label='',**kw):
    rows={m['name']:ring_scores(m,**kw) for m in MAN}
    for grp in ('bad','good'):
        a=np.array([rows[m['name']] for m in MAN if m['label']==grp]); print(f'{label:28s}{grp:5s} mean {np.nanmean(a):.3f} median {np.nanmedian(np.nanmean(a,1)):.3f}')
    return rows
if __name__=='__main__':
    rows=evaluate('baseline')
    for grp in ('bad','good'):
        a=np.array([rows[m['name']] for m in MAN if m['label']==grp]); print(grp,'by ring angle (0=right,90=up,180=left,270=down/stick):',np.nanmean(a,0).round(2))
