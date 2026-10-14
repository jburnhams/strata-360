import harness; from harness import *
from scipy.spatial.transform import Rotation as Rot
import harness as H
H.PHIS=np.arange(0,360,60)
D0=np.load('delta_front_to_rear.npy'); R=renderer(); R0=R.master.R.copy(); fx0=R.master.fx
train=[m for i,m in enumerate(MAN) if i%2==0]; test=[m for i,m in enumerate(MAN) if i%2==1]
def apply(p):
    R.master.R=R0@(Rot.from_rotvec(np.radians(p[:3])).as_matrix()@D0).T; R.master.fx=R.master.fy=fx0*(1+p[3]*1e-3)
def score(p,sets):
    apply(p); return float(np.nanmean([np.nanmean(ring_scores(m)) for m in sets]))
p=np.zeros(4); best=score(p,train); print('start train',round(best,4),'test',round(score(p,test),4),flush=True)
steps=np.array([0.3,0.3,0.3,1.0])
for rnd in range(3):
    for i in range(4):
        for sgn in (1,-1):
            while True:
                q=p.copy(); q[i]+=sgn*steps[i]; s=score(q,train)
                if s<best-1e-4: p,best=q,s
                else: break
    steps/=2; print('round',rnd,'p',p.round(3),'train',round(best,4),flush=True)
print('final train',round(best,4),'test',round(score(p,test),4),'test baseline',round(score(np.zeros(4),test),4))
np.save('refine_p.npy',p)
