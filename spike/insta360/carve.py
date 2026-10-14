import sys,time; from harness import *
sets=sys.argv[2:]; tag=sys.argv[1]
def lens16(n,t): g=cv2.imread(f'corpus/{n}_{t}_2.jpg'); g=cv2.resize(g,(3840,3840),interpolation=cv2.INTER_CUBIC); return (g[:,:,::-1].astype(np.uint16))*257
rows=[]
for n in sets:
    s=[m for m in MAN if m['name']==n][0]; cm,cs=lens16(n,'front'),lens16(n,'rear')
    R=r4.Renderer(CL[s['clip']].osv,800,450,100.0,'linear'); up=up_body(s); t0=time.time()
    R.carve_seam=True; R.parallax=True
    for nm,f in (('seamR',(1,0,0)),('seamL',(-1,0,0))):
        f=np.array(f,float); R.carve_seam=R.parallax=False; R.seam=None; R.warp=None; a=R.render(cm,cs,f,up)
        R.carve_seam=R.parallax=True; R.update_seam(cm,cs,reset=True); b=R.render(cm,cs,f,up)
        ta=((a[:,:,::-1]>>8).astype(np.uint8)).copy(); tb=((b[:,:,::-1]>>8).astype(np.uint8)).copy()
        cv2.putText(ta,n[-14:]+' '+nm+' feather',(8,28),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,255,255),2); cv2.putText(tb,'carve+parallax',(8,28),cv2.FONT_HERSHEY_SIMPLEX,0.8,(0,255,255),2)
        rows.append(np.hstack([ta,tb]))
    print(n,round(time.time()-t0,1),'s',flush=True)
cv2.imwrite(f'carve_{tag}.jpg',np.vstack(rows),[cv2.IMWRITE_JPEG_QUALITY,90])
