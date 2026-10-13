import sys, json, subprocess, os; sys.path.insert(0,'C:/Code/strata-360/src')
import numpy as np
from strata360 import oslib; oslib.lower_priority()
from strata360.pipeline import clips
from strata360.osv import insta360 as I
from strata360.osv.telemetry import video_pts
r=json.load(open('scan3.json')); items=[]
for key,v in r.items():
    if v.get('seamR') is None or v['bright']<35: continue
    cid,frac=key.split('@'); items.append((max(v['seamR'],v['seamL']),cid,float(frac),v))
items.sort(key=lambda x:x[0])
def pick(lst,n):
    out=[]; cnt={}
    for s,cid,frac,v in lst:
        if cnt.get(cid,0)>=2: continue
        cnt[cid]=cnt.get(cid,0)+1; out.append((s,cid,frac,v))
        if len(out)>=n: break
    return out
bad=pick(items[::-1],16); good=pick(items,16)
cl={c.id:c for c in clips.discover("D:/Insta360/2024-07-20 - Crossing Switzerland")[0]}
man=[]
for label,lst in (('bad',bad),('good',good)):
    for s,cid,frac,v in lst:
        c=cl[cid]; pts=video_pts(c.osv,0); k=v['k']; name=f'{label}_{cid[4:]}_{int(frac*100)}'
        for stream,tag in ((0,'rear'),(1,'front')):
            f=I.lens_file(c.osv,stream)
            subprocess.run(['ffmpeg','-v','error','-y','-ss',f'{pts[k-1]-0.002:.4f}','-i',f,'-frames:v','3','-q:v','2',f'corpus/{name}_{tag}_%d.jpg'],check=True)
        man.append(dict(name=name,label=label,clip=cid,k=k,score=s,ang=v['ang_dps'],bright=v['bright']))
json.dump(man,open('corpus/manifest.json','w'),indent=1); print(len(man),'sets', sum(os.path.getsize('corpus/'+f) for f in os.listdir('corpus'))/1e6,'MB')
