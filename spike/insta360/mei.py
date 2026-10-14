import numpy as np, re
def parse_offsets(s):
    p=s.split('_'); assert p[0]=='2'
    # per lens: xi,fx,fy,cx,cy,rot3,trans3,k1,k2,k3,p1,p2,W,H,? ; groups of 20 after the version
    v=p[1:]; L=[]
    n=20
    # fields per lens: 1+2+2+3+3+5 +3(W,H,71) = 19 ; second lens group starts afterwards; trailing number at end
    per=19
    for i in range(2):
        g=v[i*per:(i+1)*per]
        L.append(dict(xi=float(g[0]),fx=float(g[1]),fy=float(g[2]),cx=float(g[3]),cy=float(g[4]),rot=[float(x) for x in g[5:8]],tr=[float(x) for x in g[8:11]],k=[float(x) for x in g[11:14]],p=[float(x) for x in g[14:16]],W=int(g[16]),H=int(g[17]),n=int(g[18])))
    return L,v[2*per:]
def project(L,d):
    d=np.asarray(d,float); n=np.linalg.norm(d,axis=-1,keepdims=True); d=d/n
    x=d[...,0]/(d[...,2]+L['xi']); y=d[...,1]/(d[...,2]+L['xi'])
    r2=x*x+y*y; k1,k2,k3=L['k']; p1,p2=L['p']; rad=1+k1*r2+k2*r2**2+k3*r2**3
    xd=x*rad+2*p1*x*y+p2*(r2+2*x*x); yd=y*rad+p1*(r2+2*y*y)+2*p2*x*y
    return L['fx']*xd+L['cx'], L['fy']*yd+L['cy']
def unproject(L,u,v,it=20):
    xd=(np.asarray(u,float)-L['cx'])/L['fx']; yd=(np.asarray(v,float)-L['cy'])/L['fy']
    x,y=xd.copy(),yd.copy(); k1,k2,k3=L['k']; p1,p2=L['p']
    for _ in range(it):
        r2=x*x+y*y; rad=1+k1*r2+k2*r2**2+k3*r2**3
        dx=2*p1*x*y+p2*(r2+2*x*x); dy=p1*(r2+2*y*y)+2*p2*x*y
        x=(xd-dx)/rad; y=(yd-dy)/rad
    r2=x*x+y*y; xi=L['xi']; a=(xi+np.sqrt(1+(1-xi*xi)*r2))/(r2+1)
    return np.stack([a*x,a*y,a-xi],-1)
