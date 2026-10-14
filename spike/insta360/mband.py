import sys; from harness import *
from strata360.render import photo as ph
tag=sys.argv[1]; sets=sys.argv[2:]; W_,H_=800,450
def lens16(n,t): g=cv2.imread(f'corpus/{n}_{t}_2.jpg'); g=cv2.resize(g,(3840,3840),interpolation=cv2.INTER_CUBIC); return (g[:,:,::-1].astype(np.uint16))*257
rows=[]
for n in sets:
    s=[m for m in MAN if m['name']==n][0]; cm,cs=lens16(n,'front'),lens16(n,'rear'); R=r4.Renderer(CL[s['clip']].osv,W_,H_,100.0,'linear'); up=up_body(s)
    f=np.array((1,0,0),float); (um,vm,tm),(us,vs,ts)=R.maps(f,up); U=lambda a: cv2.resize(np.ascontiguousarray(a,dtype=np.float32),(W_,H_),interpolation=cv2.INTER_LINEAR)
    wm=ph.lens_weight(tm,ph.sample_occl(R.occl_m,um,vm),R.rtm,ph.RENDER_FEATHER_DEG); ws=ph.lens_weight(ts,ph.sample_occl(R.occl_s,us,vs),R.rtm,ph.RENDER_FEATHER_DEG)
    wm,ws=ph.rescue(wm,ws,tm,ts,ph.sample_occl(R.occl_m,um,vm),ph.sample_occl(R.occl_s,us,vs),ph.THETA_MAX_DEG); wn=U(np.where(wm+ws>1e-4,wm/np.maximum(wm+ws,1e-9),0))
    a=ph.EOTF_LUT[cv2.remap(cm,U(um),U(vm),cv2.INTER_LINEAR)]; b=ph.EOTF_LUT[cv2.remap(cs,U(us),U(vs),cv2.INTER_LINEAR)]
    to8=lambda lin: ((ph.linear_to_code16(lin)[:,:,::-1]>>8).astype(np.uint8)).copy()
    feather=wn[...,None]*a+(1-wn[...,None])*b
    out=[to8(feather)]
    for sig in (40,):
        wl=cv2.GaussianBlur(wn,(0,0),sig)[...,None]                       # wide transition for the low band
        la,lb=cv2.GaussianBlur(a,(0,0),12),cv2.GaussianBlur(b,(0,0),12); ha,hb=a-la,b-lb
        out.append(to8(np.clip(wl*la+(1-wl)*lb+wn[...,None]*ha+(1-wn[...,None])*hb,0,1)))
    for t,l in zip(out,('feather','2-band (low band over ~%d px)'%40)): cv2.putText(t,n[-14:]+' '+l,(8,28),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,255,255),2)
    rows.append(np.hstack(out))
cv2.imwrite(f'mband_{tag}.jpg',np.vstack(rows),[cv2.IMWRITE_JPEG_QUALITY,90])
