"""data/keiba.sqlite から可視化ページ用の集計を作り、viz/index.html を書き出す。

    python3 viz/build.py [data/keiba.sqlite]
"""
import sqlite3, pandas as pd, numpy as np, json, re, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
c=sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'data', 'keiba.sqlite'))
q=lambda s: pd.read_sql(s,c)
R=q("select r.*, x.finish, x.number, x.frame, x.horse_id,x.horse_name,x.sex,x.age,x.jockey_name,x.passing,x.last3f,x.odds,x.popularity,x.body_weight,x.body_weight_diff,x.time_sec,x.trainer_name from results x join races r using(race_id) where x.finish is not null")
R['win']=(R.finish==1).astype(int); R['top3']=(R.finish<=3).astype(int)
P=q("select p.*, r.date, r.race_no, r.venue, r.name, r.grade, r.surface, r.going, r.n_runners from payouts p join races r using(race_id)")
D={}
races=q("select count(*) n, min(date) a, max(date) b from races").iloc[0]
D['hero']=dict(races=int(races.n), runs=int(len(R)), horses=int(R.horse_id.nunique()), jockeys=int(R.jockey_name.nunique()), start=races.a, end=races.b, payouts=int(len(P)))
# popularity
g=R[R.popularity.between(1,16)].groupby('popularity')
D['pop']=[dict(p=int(k),n=int(len(v)),win=round(v.win.mean()*100,2),top3=round(v.top3.mean()*100,2),roi=round((v.win*v.odds).sum()*100/len(v),1)) for k,v in g]
# odds 1.1-2.0
b=R[(R.odds>=1.05)&(R.odds<=2.04)].copy(); b['ob']=b.odds.round(1)
D['odds']=[dict(o=float(k),n=int(len(v)),win=round(v.win.mean()*100,1)) for k,v in b.groupby('ob')]
lost11=R[(R.odds==1.1)&(R.win==0)].sort_values('date')
D['lost11']=lost11[['date','venue','name','horse_name','finish','jockey_name']].tail(8).to_dict('records')
D['lost11_n']=int(len(lost11)); D['odds11_n']=int((R.odds==1.1).sum())
# favourite cumulative
f=R[R.popularity==1].sort_values(['date','race_id']).drop_duplicates('race_id').copy()
f['ret']=np.where(f.win==1,f.odds*100,0); f['bal']=(f.ret-100).cumsum(); f['m']=f.date.str[:7]
m=f.groupby('m').agg(bal=('bal','last'),n=('bal','size')).reset_index()
D['fav']=dict(series=[[r.m,int(r.bal)] for r in m.itertuples()], stake=int(len(f)*100), ret=int(f.ret.sum()), n=int(len(f)), wins=int(f.win.sum()), maxwin=int(f.ret.max()))
# top payouts
def names(race_id, combo):
    nums=[int(x) for x in re.split(r'[-→]',combo)]
    sub=R[R.race_id==race_id].set_index('number')
    return [dict(no=n, name=str(sub.loc[n,'horse_name']) if n in sub.index else '', pop=int(sub.loc[n,'popularity']) if n in sub.index and pd.notna(sub.loc[n,'popularity']) else None) for n in nums]
t=P[P.bet_type=='三連単'].sort_values('payout',ascending=False).head(10)
D['top3t']=[dict(date=r.date,venue=r.venue,race_no=int(r.race_no),name=r.name,payout=int(r.payout),pop=int(r.popularity),n=int(r.n_runners),horses=names(r.race_id,r.combo)) for r in t.itertuples()]
t3=P[P.bet_type=='三連単']
D['t3count']=int(len(t3)); D['t3_over1m']=int((t3.payout>=1_000_000).sum()); D['t3_median']=int(t3.payout.median())
# biggest win odds
w=R[R.win==1]
D['upsets']=w.sort_values('odds',ascending=False).head(6)[['date','venue','race_no','name','horse_name','odds','popularity','n_runners','jockey_name']].to_dict('records')
# race number
t3['big']=t3.payout>=100000
rn=t3.groupby('race_no').agg(med=('payout','median'),big=('big','mean')).reset_index()
fav_rn=R[R.popularity==1].groupby('race_no').win.mean()
D['raceno']=[dict(r=int(x.race_no),med=int(x.med),big=round(x.big*100,1),fav=round(fav_rn[x.race_no]*100,1)) for x in rn.itertuples()]
# going x surface
gs=[]
for s in ['芝','ダ']:
    for go in ['良','稍重','重','不良']:
        sub=t3[(t3.surface==s)&(t3.going==go)]; fv=R[(R.surface==s)&(R.going==go)&(R.popularity==1)]
        gs.append(dict(s=s,g=go,n=int(len(sub)),med=int(sub.payout.median()),big=round(sub.big.mean()*100,1),fav=round(fv.win.mean()*100,1)))
D['going']=gs
# jockey day record
jd=w.groupby(['date','jockey_name']).agg(n=('win','size'),venue=('venue','first')).reset_index().sort_values('n',ascending=False)
D['jday']=jd.head(5).to_dict('records')
rides=R.groupby(['date','jockey_name']).size()
D['jday_rides']={f"{r.date}|{r.jockey_name}":int(rides[(r.date,r.jockey_name)]) for r in jd.head(5).itertuples()}
# body weight
bw=R[R.body_weight.notna()&(R.surface!='障')].copy()
bins=[0,420,440,460,480,500,520,540,999]; labels=['〜419','420〜439','440〜459','460〜479','480〜499','500〜519','520〜539','540〜']
bw['bin']=pd.cut(bw.body_weight,bins,right=False,labels=labels)
D['bw']=[dict(b=str(k),n=int(len(v)),win=round(v.win.mean()*100,2)) for k,v in bw.groupby('bin',observed=True)]
bd=bw[bw.body_weight_diff.notna()].copy()
bd['d']=pd.cut(bd.body_weight_diff,[-99,-19,-9,-3,3,10,20,99],labels=['-20以下','-10〜-19','-4〜-9','±3','+4〜+10','+11〜+20','+21以上'])
D['bwd']=[dict(b=str(k),n=int(len(v)),win=round(v.win.mean()*100,2)) for k,v in bd.groupby('d',observed=True)]
wb=w[w.body_weight.notna()]
D['bw_ext']=[wb.loc[wb.body_weight.idxmax(),['date','venue','name','horse_name','body_weight']].to_dict(), wb.loc[wb.body_weight.idxmin(),['date','venue','name','horse_name','body_weight']].to_dict()]
# horse records
h=R.groupby(['horse_id','horse_name']).agg(n=('win','size'),wins=('win','sum'),top3=('top3','sum')).reset_index()
D['most_wins']=h.sort_values(['wins','n'],ascending=[False,True]).head(5).to_dict('records')
D['most_runs']=h.sort_values('n',ascending=False).head(5).to_dict('records')
D['no_win']=h[h.wins==0].sort_values('n',ascending=False).head(5).to_dict('records')
# name length
nl=R[R.horse_name.str.len().between(2,9)].copy(); nl['nl']=nl.horse_name.str.len()
D['namelen']=[dict(l=int(k),n=int(len(v)),win=round(v.win.mean()*100,2),ex=v.drop_duplicates('horse_id').sort_values('win',ascending=False).horse_name.iloc[0]) for k,v in nl.groupby('nl')]
D['name2']=nl[nl.nl==2].groupby('horse_name').win.sum().sort_values(ascending=False).head(6).index.tolist()
# age
ag=R[(R.surface!='障')&R.age.between(2,9)]
D['age']=[dict(a=int(k),n=int(len(v)),win=round(v.win.mean()*100,2)) for k,v in ag.groupby('age')]
# running style
def first_pos(p):
    try: return int(str(p).split('-')[0])
    except: return None
R['fp']=R.passing.map(first_pos)
rs=R[R.fp.notna()&(R.surface!='障')].copy()
fr=rs.fp/rs.n_runners
rs['style']=np.select([rs.fp==1, fr<=1/3, fr<=2/3],['逃げ','先行','差し'],'追込')
D['style']=[dict(s=s,st=st,n=int(len(v)),win=round(v.win.mean()*100,2)) for (s,st),v in rs.groupby(['surface','style'])]
# fastest last3f
l=R[R.last3f.notna()&(R.surface!='障')].copy()
mn=l.groupby('race_id').last3f.transform('min'); cnt=l[l.last3f==mn].groupby('race_id').size()
l=l[(l.last3f==mn)]; l=l[l.race_id.map(cnt)==1]
D['l3f']=[dict(s=s,n=int(len(v)),win=round(v.win.mean()*100,1),top3=round(v.top3.mean()*100,1)) for s,v in l.groupby('surface')]
D['nige_venue']=[dict(v=v,s=s,n=int(len(x)),win=round(x.win.mean()*100,1)) for (v,s),x in rs[rs['style']=='逃げ'].groupby(['venue','surface'])]
# frame bias by course
fb=R[(R.n_runners>=14)&(R.surface!='障')&R.frame.notna()].copy()
fb['course']=fb.venue+' '+fb.surface+fb.distance.astype(str)+'m'
cnt=fb.groupby('course').race_id.nunique(); keep=cnt[cnt>=150].index
courses=[]
for cname in keep:
    x=fb[fb.course==cname]; fr_=x.groupby('frame').win.mean()*100
    inner=x[x.frame<=2].win.mean(); outer=x[x.frame>=7].win.mean()
    courses.append(dict(c=cname,races=int(cnt[cname]),f=[round(fr_.get(i,0),2) for i in range(1,9)],ratio=round(inner/outer,2)))
courses.sort(key=lambda d:-d['races'])
D['frames']=courses
# kikka history
k=q("select r.race_id,r.date,r.going,r.laps from races r where name like '%菊花賞%' order by date")
kh=[]
for r in k.itertuples():
    x=R[R.race_id==r.race_id].sort_values('finish')
    wn=x.iloc[0]; t=P[(P.race_id==r.race_id)&(P.bet_type=='三連単')]
    kh.append(dict(year=int(r.date[:4]),date=r.date,going=r.going,winner=wn.horse_name,pop=int(wn.popularity),odds=float(wn.odds),jockey=wn.jockey_name,time=float(wn.time_sec),pass_=wn.passing,last3f=float(wn.last3f),frame=int(wn.frame),t3=int(t.payout.iloc[0]) if len(t) else None,
      top3=[dict(name=y.horse_name,pop=int(y.popularity)) for y in x.head(3).itertuples()]))
D['kikka']=kh
# bar chart races (monthly cumulative wins)
def race_series(df,key,topn=10):
    df=df.copy(); df['m']=df.date.str[:7]
    piv=df.groupby(['m',key]).size().unstack(fill_value=0).sort_index().cumsum()
    ents=set()
    for m_,row in piv.iterrows(): ents|=set(row.nlargest(topn+2).index)
    piv=piv[sorted(ents)]
    return dict(months=list(piv.index), names=list(piv.columns), values=piv.T.values.tolist())
D['race_jockey']=race_series(w,'jockey_name')
hs=q("select horse_id, sire from horses")
ws=w.merge(hs,on='horse_id'); ws['sire']=ws.sire.str.replace('\xa0',' ')
D['race_sire']=race_series(ws,'sire')
data=json.dumps(D,ensure_ascii=False,default=lambda o: o.item() if hasattr(o,'item') else str(o))
src=open(os.path.join(HERE,'page.src.html'),encoding='utf-8').read()
open(os.path.join(HERE,'index.html'),'w',encoding='utf-8').write(src.replace('/*DATA*/null',data))
print('wrote viz/index.html', len(data), 'bytes of data')
