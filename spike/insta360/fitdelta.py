import sys; sys.path.insert(0,'.'); sys.path.insert(0,'C:/Code/strata-360/src')
import numpy as np, cv2, json
from scipy.spatial.transform import Rotation as Rot
from mei import unproject
from strata360.osv import insta360 as I
from harness import MAN, CL
L=I.parse_calibration(I.extra(next(iter(CL.values())).osv)['calibration'])
def body_dirs(px,py,lens,Rm):
    d=unproject(lens,(px+48)*2,(py+48)*2); return d@Rm            # (Rm rows = lens axes in body) d_body = Rm^T d_lens -> row vectors: d @ Rm
sift=cv2.SIFT_create(9000)
def kabsch(A,B):
    H=A.T@B; U,S,Vt=np.linalg.svd(H); D=np.diag([1,1,np.linalg.det(Vt.T@U.T)]); return Vt.T@D@U.T
Fa,Fb=[],[]; per=[]
for s in MAN:
    n=s['name']; r=cv2.imread(f'corpus/{n}_rear_2.jpg',0); f=cv2.imread(f'corpus/{n}_front_2.jpg',0)
    yy,xx=np.mgrid[0:2880,0:2880]; rad=np.hypot(xx-1440,yy-1440); mask=((rad>900)&(rad<1425)).astype(np.uint8)*255
    kr,dr=sift.detectAndCompute(r,mask); kf,df=sift.detectAndCompute(f,mask)
    if dr is None or df is None or len(kr)<20 or len(kf)<20: continue
    m=[a for a,b in cv2.BFMatcher().knnMatch(dr,df,k=2) if a.distance<0.8*b.distance] if True else []
    mm=cv2.BFMatcher().knnMatch(dr,df,k=2); m=[a for a,b in mm if a.distance<0.8*b.distance]
    if len(m)<8: continue
    pr=np.array([kr[a.queryIdx].pt for a in m]); pf=np.array([kf[a.trainIdx].pt for a in m])
    dr_=body_dirs(pr[:,0],pr[:,1],L[0],I._R_REAR); df_=body_dirs(pf[:,0],pf[:,1],L[1],I._R_FRONT)
    ok=np.isfinite(dr_).all(1)&np.isfinite(df_).all(1); dr_,df_=dr_[ok],df_[ok]
    if len(dr_)<8: continue
    best=None; rng=np.random.default_rng(0)
    for _ in range(300):
        i=rng.choice(len(dr_),min(4,len(dr_)),replace=False); Rm=kabsch(df_[i],dr_[i]); e=np.degrees(np.arccos(np.clip((dr_*(df_@Rm.T)).sum(1),-1,1))); c=(e<1.5).sum()
        if best is None or c>best[0]: best=(c,e<1.5)
    if best[0]<6: continue
    Fa.append(df_[best[1]]); Fb.append(dr_[best[1]]); per.append((n,int(best[0])))
A=np.vstack(Fa); B=np.vstack(Fb); D=kabsch(A,B); e0=np.degrees(np.arccos(np.clip((B*A).sum(1),-1,1))); e1=np.degrees(np.arccos(np.clip((B*(A@D.T)).sum(1),-1,1)))
print('sets used',len(per),'matches',len(A)); print('rms before %.3f after %.3f deg'%(np.sqrt((e0**2).mean()),np.sqrt((e1**2).mean()))); print('delta rotvec deg',np.degrees(Rot.from_matrix(D).as_rotvec()).round(3))
np.save('delta_front_to_rear.npy',D)
# per-set consistency
for (n,c),a,b in list(zip(per,Fa,Fb))[:0]: pass
rv=[np.degrees(Rot.from_matrix(kabsch(a,b)).as_rotvec()) for a,b in zip(Fa,Fb)]; print('per-set rotvec spread (std deg)',np.std(rv,0).round(2))
