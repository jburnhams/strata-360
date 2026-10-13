import sys, os, json, time; sys.path.insert(0,'C:/Code/strata-360/src')
import numpy as np, cv2
from strata360 import oslib; oslib.lower_priority()
from strata360.pipeline import clips
from strata360.render import flat as r4, photo as ph
from strata360.osv.telemetry import read_frames, video_pts
cam=sys.argv[1]; OUT=f'cmp_{cam}.json'; W,H=800,450; os.makedirs('cmp_img',exist_ok=True)
res=json.load(open(OUT)) if os.path.exists(OUT) else {}
VAR=['feather','gain','mb','gain+mb','mb+match']
def gray(img16): return cv2.cvtColor((img16>>8).astype(np.uint8),cv2.COLOR_RGB2GRAY).astype(np.float32)
def G(x,s): return cv2.GaussianBlur(x,(0,0),s)
def grad(x): gx=cv2.Sobel(x,cv2.CV_32F,1,0,ksize=3); gy=cv2.Sobel(x,cv2.CV_32F,0,1,ksize=3); return np.hypot(gx,gy)
def sets():
    if cam=='insta':
        sys.path.insert(0,'.'); import harness as Hn
        for m in Hn.MAN:
            def lens(n=m['name']):
                f=lambda t: (cv2.resize(cv2.imread(f'corpus/{n}_{t}_2.jpg'),(3840,3840),interpolation=cv2.INTER_CUBIC)[:,:,::-1].astype(np.uint16))*257
                return f('front'),f('rear')
            yield m['name'],Hn.CL[m['clip']].osv,m['k'],lens
    else:
        cl,_=clips.discover("D:/Insta360/2026-02-19 - Legends")
        for c in cl:
            pts=video_pts(c.osv,0); k=int(len(pts)*0.4)
            def lens(c=c,k=k,pts=pts):
                ss=max(pts[k]-0.002,0); dm=r4.decoder(c.osv,1,hw=False,ss=ss); ds=r4.decoder(c.osv,0,hw=False,ss=ss); a=r4.read_frame(dm); b=r4.read_frame(ds); dm.kill(); ds.kill(); return a,b
            yield c.id,c.osv,k,lens
for name,osv,k,lensf in sets():
    if name in res: continue
    try:
        t0=time.time(); cm,cs=lensf(); R=r4.Renderer(osv,W,H,100.0,'linear'); tel=read_frames(osv); up=R.stab_matrix(tel['quat'][k])@np.array([0,0,1.0])
        gm,gs,_=ph.estimate_gain(cm,cs,R.master,R.slave,R.occl_m,R.occl_s); per={}; imgs={}
        for vn,f in (('R',(1,0,0)),('L',(-1,0,0))):
            f=np.array(f,float); (um,vm,tm),(us,vs,ts)=R.maps(f,up); U=lambda a: cv2.resize(np.ascontiguousarray(a,dtype=np.float32),(W,H),interpolation=cv2.INTER_LINEAR)
            wm=ph.lens_weight(tm,ph.sample_occl(R.occl_m,um,vm),R.rtm,ph.RENDER_FEATHER_DEG); ws=ph.lens_weight(ts,ph.sample_occl(R.occl_s,us,vs),R.rtm,ph.RENDER_FEATHER_DEG)
            band=(U(wm)>1e-3)&(U(ws)>1e-3); band=cv2.dilate(band.astype(np.uint8),np.ones((5,5)))>0
            if band.sum()<500: continue
            ga=gray(cv2.remap(cm,U(um),U(vm),cv2.INTER_LINEAR)); gb=gray(cv2.remap(cs,U(us),U(vs),cv2.INTER_LINEAR)); nat=np.mean([np.percentile(grad(G(g,3))[band],95) for g in (ga,gb)]); S=12; nat2=np.mean([np.percentile(grad(G(g,S))[band],95) for g in (ga,gb)])
            for var in VAR:
                R.multiband=var in('mb','gain+mb','mb+match'); R.mb_match=var=='mb+match'
                R.set_gains(*(gm,gs)) if 'gain' in var else R.set_gains(np.ones(3),np.ones(3))
                out=R.render(cm,cs,f,up); g=gray(out); step=float(np.percentile(grad(G(g,3))[band],95)/max(nat,1e-3)); det=float(np.abs(G(g,1)-G(g,3))[band].mean()); step2=float(np.percentile(grad(G(g,S))[band],95)/max(nat2,1e-3))
                per.setdefault(var,{})[vn]=dict(step=step,step2=step2,detail=det); imgs[(var,vn)]=out
        for vn in 'RL':                                                                  # keep a panel for the clearest cases
            if all((v,vn) in imgs for v in VAR):
                p=[cv2.putText(((imgs[(v,vn)][:,:,::-1]>>8).astype(np.uint8)).copy(),f'{name[-18:]} {vn} {v}',(8,26),cv2.FONT_HERSHEY_SIMPLEX,0.7,(0,255,255),2) for v in VAR]
                cv2.imwrite(f'cmp_img/{cam}_{name}_{vn}.jpg',cv2.resize(np.vstack([np.hstack(p[:3]),np.hstack(p[3:]+[np.zeros_like(p[0])])]),None,fx=0.5,fy=0.5,interpolation=cv2.INTER_AREA),[cv2.IMWRITE_JPEG_QUALITY,85])
        res[name]=dict(sec=round(time.time()-t0,1),**{v:per.get(v) for v in VAR})
    except Exception as e: res[name]=dict(error=str(e)[:200])
    json.dump(res,open(OUT,'w')); print(name,res[name].get('error','ok'),res[name].get('sec'),flush=True)
