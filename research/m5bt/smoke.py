import glob,os,numpy as np, json
import signals as S, engine as E, build as B, analyze as A
syms=sorted(os.path.basename(p)[:-4] for p in glob.glob("pq/*.npz"))[:60]
tot=0
for s in syms:
    try: sg,arrs=S.sigs_for(s)
    except Exception as e: print("err",s,e); continue
    if sg: tot+=len(sg); print(s,len(sg),[round(x[3],1) for x in sg[:3]])
print("total signals in first 60 syms:",tot)
cf=A.build_grid(); print("grid size:",len(cf))
print(list(cf.items())[:6])
