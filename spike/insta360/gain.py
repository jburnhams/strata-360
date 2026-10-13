import sys,time; from harness import *
from strata360.render import photo as ph
tag=sys.argv[1]; sets=sys.argv[2:]
def lens16(n,t): g=cv2.imread(f'corpus/{n}_{t}_2.jpg'); g=cv2.resize(g,(3840,3840),interpolation=cv2.INTER_CUBIC); return (g[:,:,::-1].astype(np.uint16))*257
rows=[]
for n in sets:
    s=[m for m in MAN if m['name']==n][0]; cm,cs=lens16(n,'front'),lens16(n,'rear'); R=r4.Renderer(CL[s['clip']].osv,800,450,100.0,'linear'); up=up_body(s)
    gm,gs,cnt=ph.estimate_gain(cm,cs,R.master,R.slave,R.occl_m,R.occl_s); print(n,'gain front',gm.round(3),'rear',gs.round(3),'trusted px',cnt,flush=True)
    f=np.array((1,0,0),float); tiles=[]
    for lab,gains,carve in (('feather',None,False),('carve',None,True),('carve+gain',(gm,gs),True)):
        R.set_gains(np.ones(3),np.ones(3)) if gains is None else R.set_gains(*gains)
        R.carve_seam=R.parallax=carve; R.seam=None; R.warp=None
        if carve: R.update_seam(cm,cs,reset=True)
        a=R.render(cm,cs,f,up); t=((a[:,:,::-1]>>8).astype(np.uint8)).copy(); cv2.putText(t,n[-14:]+' '+lab,(8,28),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,255,255),2); tiles.append(t)
    rows.append(np.hstack(tiles))
cv2.imwrite(f'gain_{tag}.jpg',cv2.resize(np.vstack(rows),None,fx=0.7,fy=0.7,interpolation=cv2.INTER_AREA),[cv2.IMWRITE_JPEG_QUALITY,90])
