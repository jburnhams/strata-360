import sys; from harness import *
R=r4.Renderer(next(iter(CL.values())).osv,960,540,100.0,'linear')
def lens16(name,tag): g=cv2.imread(f'corpus/{name}_{tag}_2.jpg'); g=cv2.resize(g,(3840,3840),interpolation=cv2.INTER_CUBIC); return (g[:,:,::-1].astype(np.uint16))*257
names=sys.argv[2:]; tag=sys.argv[1]; rows=[]
for n in names:
    s=[m for m in MAN if m['name']==n][0]; up=up_body(s); cm,cs=lens16(n,'front'),lens16(n,'rear'); tiles=[]
    for nm,f in (('seamR',(1,0,0)),('seamL',(-1,0,0)),('stick-down',(0,-0.2,-1))):
        f=np.array(f,float); f/=np.linalg.norm(f); img=R.render(cm,cs,f,up); t=((img[:,:,::-1]>>8).astype(np.uint8)).copy(); cv2.putText(t,n[-14:]+' '+nm,(10,35),cv2.FONT_HERSHEY_SIMPLEX,1,(0,255,255),2); tiles.append(t)
    rows.append(np.hstack(tiles))
cv2.imwrite(f'stitch_{tag}.jpg',cv2.resize(np.vstack(rows),None,fx=0.67,fy=0.67,interpolation=cv2.INTER_AREA),[cv2.IMWRITE_JPEG_QUALITY,90])
