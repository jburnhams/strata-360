import sys, os, json, time; sys.path.insert(0,'C:/Code/strata-360/src')
import numpy as np, cv2
from strata360 import oslib
oslib.lower_priority()
from strata360.pipeline import clips
from strata360.render import flat as r4
from strata360.osv.telemetry import read_frames, video_pts
OUT='scan3.json'; W,H=640,360
cl,_=clips.discover("D:/Insta360/2024-07-20 - Crossing Switzerland")
res=json.load(open(OUT)) if os.path.exists(OUT) else {}
def gray(img16): return cv2.cvtColor((img16>>8).astype(np.uint8),cv2.COLOR_RGB2GRAY)
for c in cl:
    pts=video_pts(c.osv,0); tel=read_frames(c.osv); R=None
    for frac in (0.25,0.5,0.75):
        key=f'{c.id}@{frac}'
        if key in res: continue
        try:
            k=int(len(pts)*frac); ss=max(pts[k]-0.002,0)
            if R is None: R=r4.Renderer(c.osv,W,H,100.0,'linear')
            dm=r4.decoder(c.osv,1,hw=False,ss=ss); ds=r4.decoder(c.osv,0,hw=False,ss=ss); cm=r4.read_frame(dm); cs=r4.read_frame(ds); dm.kill(); ds.kill()
            M=R.stab_matrix(tel['quat'][k]); up_b=M@np.array([0,0,1.0]); gm,gs=gray(cm),gray(cs); met=dict(k=k)
            q=tel['quat']; w=np.degrees(2*np.arccos(np.clip(abs(np.sum(q[max(k-3,0)]*q[min(k+3,len(q)-1)])),0,1)))/(6/29.97); met['ang_dps']=float(w); met['bright']=float(gm.mean()+gs.mean())/2
            for name,f in (('seamR',(1,0,0)),('seamL',(-1,0,0))):
                f=np.array(f,float); (um,vm,tm),(us,vs,ts)=R.maps(f,up_b)
                a=cv2.GaussianBlur(cv2.remap(gm,um.astype(np.float32),vm.astype(np.float32),cv2.INTER_LINEAR).astype(float),(0,0),1.5); b=cv2.GaussianBlur(cv2.remap(gs,us.astype(np.float32),vs.astype(np.float32),cv2.INTER_LINEAR).astype(float),(0,0),1.5)
                m=(tm<92)&(ts<92); met[name]=float(np.abs(a-b)[m].mean()/max(a[m].mean(),1)) if m.sum()>50 else None
            res[key]=met
        except Exception as e: res[key]=dict(error=str(e)[:150])
    json.dump(res,open(OUT,'w')); print(c.id,flush=True)
