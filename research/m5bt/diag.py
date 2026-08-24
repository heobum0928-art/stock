import os,pickle,numpy as np,json
import engine as E, analyze as A
D=os.path.dirname(os.path.abspath(__file__))
dat=pickle.load(open(os.path.join(D,"events.pkl"),"rb")) if os.path.exists(os.path.join(D,"events.pkl")) else None
if dat is None:
    import build; dat=build.main()
    pickle.dump(dat,open(os.path.join(D,"events.pkl"),"wb"),4)
real=dat["real"]
cf=[]; wf=[]; nof=[]
for r in real:
    a=E.evaluate(r["opt"],None,0,40,40,funding_fn=E.funding)["ret"]
    b=E.evaluate(r["opt"],None,0,40,40,funding_fn=None)["ret"]
    wf.append(a); nof.append(b); cf.append(a-b)
wf=np.array(wf); nof=np.array(nof); cf=np.array(cf)
print("single-40 WITH funding   mean %.2f%%  median %.2f%%  win %.1f%%"%(wf.mean()*100,np.median(wf)*100,(wf>0).mean()*100))
print("single-40 NO   funding   mean %.2f%%  median %.2f%%  win %.1f%%"%(nof.mean()*100,np.median(nof)*100,(nof>0).mean()*100))
print("funding P&L: mean %.2f%%  median %.2f%%  p5 %.2f%%  p95 %.2f%%  min %.2f%%  max %.2f%%"%(
    cf.mean()*100,np.median(cf)*100,np.percentile(cf,5)*100,np.percentile(cf,95)*100,cf.min()*100,cf.max()*100))
print("share of trades where funding hurt short:", (cf<0).mean())
# funding interval distribution
import glob
iv=[]
for p in glob.glob(os.path.join(D,"fund","*.npz"))[:400]:
    z=np.load(p); t=z[z.files[0]]
    if len(t)>10: iv.append(np.median(np.diff(t))/3600000)
iv=np.array(iv); print("median funding interval (h) across symbols:", np.percentile(iv,[5,25,50,75,95]))
# cost decomposition
print("\nprice-only (no funding, no cost):")
po=[]
for r in real:
    se=r["opt"]
    res=E.evaluate(se,None,0,40,40,funding_fn=None)
    po.append(res)
kinds={}
for x in po: kinds[x["kind"]]=kinds.get(x["kind"],0)+1
print("exit reason mix (single-40, low-first):",kinds)
