"""사용자 제안 검증: 손절 끄고 회복을 기다리면? (격자탐색 아님 — 지정된 설정 몇 개만)"""
import pickle, numpy as np, engine as E
d=pickle.load(open('events.pkl','rb'))
LIQ=E.LEVELS[-1]
print("청산(강제) 선: 역행 %.2f%% (명목)  / 현행 손절선: 40%% (명목)"%LIQ)
print("=> 손절선과 강제청산 사이 여유: %.2f%%p\n"%(LIQ-40.0))
cfgs=[("현행 (손절-40% + 트레일링)",40.0,True),
      ("손절 끔 — 강제청산까지 버팀",LIQ,True),
      ("손절 끔 + 트레일링도 끔 (48h 완주)",LIQ,False)]
for name,F,use_trail in cfgs:
    rets=[];liqs=[]
    for r in d['real']:
        se=r['opt']; save=se.trail
        if not use_trail: se.trail=None
        o=E.evaluate(se,None,0.0,F,F,funding_fn=E.funding)
        se.trail=save
        rets.append(o['ret']*100); liqs.append(o['liq'])
    x=np.array(rets); lq=np.array(liqs)
    print(f"{name:38s} 평균 {x.mean():+7.2f}%  중앙 {np.median(x):+6.2f}%  "
          f"강제청산 {lq.mean()*100:5.1f}%  승률 {(x>0).mean()*100:.1f}%")
