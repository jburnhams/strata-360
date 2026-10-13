import json,sys,numpy as np
cam=sys.argv[1]; r=json.load(open(f'cmp_{cam}.json')); VAR=['feather','gain','mb','gain+mb','mb+match']
ok={k:v for k,v in r.items() if 'error' not in v and v.get('feather')}; print(cam,len(ok),'ok of',len(r),'| errors',[v['error'][:60] for v in r.values() if 'error' in v][:2])
def table(names,label):
    print(label,len(names),'sets')
    for var in VAR:
        K='step2'; st=np.array([np.mean([ok[n][var][vn][K] for vn in ok[n][var]]) for n in names]); st0=np.array([np.mean([ok[n]['feather'][vn][K] for vn in ok[n]['feather']]) for n in names])
        de=np.array([np.mean([ok[n][var][vn]['detail']/max(ok[n]['feather'][vn]['detail'],1e-6) for vn in ok[n][var]]) for n in names])
        print(f'  {var:9s} step median {np.median(st):.3f} (feather {np.median(st0):.3f}) mean {st.mean():.3f} | sets better than feather {int((st<st0-0.02).sum()):2d} worse {int((st>st0+0.02).sum()):2d} | detail kept {np.median(de):.3f} min {de.min():.3f}')
names=sorted(ok); 
if cam=='insta':
    table([n for n in names if n.startswith('bad')],'bad'); table([n for n in names if n.startswith('good')],'good')
else: table(names,'all')
# worst by feather step
w=sorted(names,key=lambda n:-np.mean([ok[n]['feather'][vn]['step2'] for vn in ok[n]['feather']]))[:5]; print('worst feather:',[(n[-22:],round(float(np.mean([ok[n]['feather'][vn]['step2'] for vn in ok[n]['feather']])),2)) for n in w])
