import numpy as np, engine as E

def mk(prices):
    p=np.array(prices,float)
    o=p.copy(); c=p.copy(); h=p.copy(); l=p.copy()
    return o,h,l,c

def se_of(prices, P0, opt=True):
    o,h,l,c = mk(prices)
    f,tr,ex,mae,mfe = E.scan(h,l,o,c,P0,opt=opt)
    return E.SigEvents(f,tr,ex,mae,mfe,P0,0,np.arange(len(c))*300000,len(c))

P0=100.0
# T1: monotone rise to 150
se = se_of([100*(1+0.01*i) for i in range(1,60)], P0)
print("single40:", E.evaluate(se,None,0,40,40))
print("staged 12/.5/25/40:", E.evaluate(se,12.0,0.5,25.0,40.0))
print("single20:", E.evaluate(se,None,0,20,20))
# T2: monotone fall to 70 then flat -> expiry
se2 = se_of([100*(1-0.01*i) for i in range(1,31)]+[70]*10, P0)
print("fall single40:", E.evaluate(se2,None,0,40,40))
# T3: fall to 80 (fav 20, armed) then rise back to 95 -> trail exit at fav 10 => price 90
se3 = se_of([98,95,90,85,80,82,85,88,90,92,95,95,95], P0)
r=E.evaluate(se3,None,0,40,40); print("trail:", r, " expect exit price 90 -> ret ~ +0.2-costs")
# T4: gap above liquidation
se4 = se_of([101,102,150,150], P0)
print("gap-liq single40:", E.evaluate(se4,None,0,40,40))
print("gap-liq staged:", E.evaluate(se4,12.0,0.5,25.0,40.0))
