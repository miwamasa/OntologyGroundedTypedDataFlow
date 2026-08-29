from __future__ import annotations
from collections import defaultdict
import numpy as np
from scipy.linalg import expm
from .frame import SemanticFrame
from .types import SemanticType, Quality, require_kind, require_same_universe, join_quality
from .utils import CANON_BANDS, band_start

LIVING=["S","M","W","V"]
ABSORB=["D_S","D_M","D_W","D_V"]
IDX={s:i for i,s in enumerate(LIVING+ABSORB)}

def _lookup(frame, *, year, sex):
    return [r for r in frame.rows if r.get("year")==year and r.get("sex")==sex]

def observed_share(census: SemanticFrame, year: int, sex: str) -> SemanticFrame:
    require_kind(census.type,"MaritalPopulation","observed_share")
    pop=defaultdict(float)
    for r in _lookup(census,year=year,sex=sex): pop[(r["age"],r["state"])]+=r["value"]
    out=[]
    for age in CANON_BANDS:
        den=sum(pop[(age,s)] for s in LIVING)
        if den<=0: continue
        for s in LIVING: out.append({"year":year,"sex":sex,"age":age,"state":s,"value":pop[(age,s)]/den})
    t=SemanticType("MaritalShare",census.type.dims,"proportion",census.type.age_scheme,census.type.universe,"Period",Quality.OBSERVED)
    return SemanticFrame(f"share_{year}",t,out,census.provenance+ [f"observed marital shares for {year}"])

def extrapolate_share(census: SemanticFrame, base_years: list[int], target_year: int, sex: str) -> SemanticFrame:
    require_kind(census.type,"MaritalPopulation","extrapolate_share")
    y0,y1=base_years
    s0=observed_share(census,y0,sex); s1=observed_share(census,y1,sex)
    d0={(r['age'],r['state']):r['value'] for r in s0.rows}; d1={(r['age'],r['state']):r['value'] for r in s1.rows}
    factor=(target_year-y1)/(y1-y0)
    out=[]
    for age in CANON_BANDS:
        raw={s:max(0.0,d1.get((age,s),0)+factor*(d1.get((age,s),0)-d0.get((age,s),0))) for s in LIVING}
        z=sum(raw.values())
        if z<=0: continue
        for s in LIVING: out.append({"year":target_year,"sex":sex,"age":age,"state":s,"value":raw[s]/z})
    t=SemanticType("MaritalShare",s1.type.dims,"proportion",s1.type.age_scheme,s1.type.universe,"Period",Quality.ESTIMATED,
                   note=f"linear extrapolation {y0}->{y1}->{target_year}")
    return SemanticFrame(f"share_{target_year}",t,out,census.provenance,
                         [f"linear extrapolation of marital shares from {y0},{y1} to {target_year}; clipped at zero and renormalized"])

def partition_exposure(exposure: SemanticFrame, share: SemanticFrame, year: int, sex: str) -> SemanticFrame:
    require_kind(exposure.type,"Exposure","partition_exposure"); require_kind(share.type,"MaritalShare","partition_exposure")
    require_same_universe(exposure.type,share.type,"partition_exposure")
    e={(r['age']):r['value'] for r in _lookup(exposure,year=year,sex=sex)}
    out=[]
    for r in _lookup(share,year=year,sex=sex):
        if r['age'] in e: out.append({**r,"value":r['value']*e[r['age']]})
    t=SemanticType("StateExposure",frozenset({"year","sex","age","state"}),"person-year",exposure.type.age_scheme,
                   exposure.type.universe,"Period",join_quality(exposure.type,share.type))
    return SemanticFrame("state_exposure",t,out,exposure.provenance+share.provenance,share.assumptions)

def death_hazard(deaths: SemanticFrame, state_exposure: SemanticFrame, year: int, sex: str) -> SemanticFrame:
    require_kind(deaths.type,"DeathCount","death_hazard"); require_kind(state_exposure.type,"StateExposure","death_hazard")
    require_same_universe(deaths.type,state_exposure.type,"death_hazard")
    d=defaultdict(float); e=defaultdict(float)
    for r in _lookup(deaths,year=year,sex=sex): d[(r['age'],r['state'])]+=r['value']
    for r in _lookup(state_exposure,year=year,sex=sex): e[(r['age'],r['state'])]+=r['value']
    out=[]
    for age in CANON_BANDS:
        for s in LIVING:
            den=e[(age,s)]; val=d[(age,s)]/den if den>0 else 0.0
            out.append({"year":year,"sex":sex,"age":age,"from_state":s,"to_state":"D","value":val})
    t=SemanticType("HazardRate",frozenset({"year","sex","age","from_state","to_state"}),"1/year",deaths.type.age_scheme,
                   deaths.type.universe,"Period",join_quality(deaths.type,state_exposure.type),target_state="D")
    return SemanticFrame("death_hazard",t,out,deaths.provenance+state_exposure.provenance,state_exposure.assumptions)

def transition_hazards(frames: list[SemanticFrame], state_exposure: SemanticFrame, year: int, sex: str) -> SemanticFrame:
    require_kind(state_exposure.type,"StateExposure","transition_hazards")
    e={(r['age'],r['state']):r['value'] for r in _lookup(state_exposure,year=year,sex=sex)}
    out=[]; q=state_exposure.type.quality; prov=list(state_exposure.provenance); assumptions=list(state_exposure.assumptions)
    for f in frames:
        require_kind(f.type,"TransitionCount","transition_hazards")
        q=join_quality(SemanticType("x",quality=q),f.type); prov += f.provenance; assumptions += f.assumptions
        agg=defaultdict(float)
        for r in _lookup(f,year=year,sex=sex): agg[(r['age'],r['from_state'],r['to_state'])]+=r['value']
        for (age,src,dst),num in agg.items():
            den=e.get((age,src),0.0)
            out.append({"year":year,"sex":sex,"age":age,"from_state":src,"to_state":dst,"value":num/den if den>0 else 0.0})
    t=SemanticType("HazardRate",frozenset({"year","sex","age","from_state","to_state"}),"1/year",state_exposure.type.age_scheme,
                   state_exposure.type.universe,"Period",q)
    return SemanticFrame("transition_hazard",t,out,prov,assumptions)

def generator_matrix(death: SemanticFrame, transitions: SemanticFrame, year: int, sex: str) -> SemanticFrame:
    require_kind(death.type,"HazardRate","generator_matrix"); require_kind(transitions.type,"HazardRate","generator_matrix")
    by_age={a:np.zeros((8,8),dtype=float) for a in CANON_BANDS}
    for f in [transitions,death]:
        for r in _lookup(f,year=year,sex=sex):
            age,src,dst,val=r['age'],r['from_state'],r['to_state'],max(0.0,float(r['value']))
            if age not in by_age or src not in LIVING: continue
            i=IDX[src]
            if dst=="D": j=IDX[f"D_{src}"]
            elif dst in LIVING: j=IDX[dst]
            else: continue
            by_age[age][i,j]+=val
    out=[]
    for age,G in by_age.items():
        for s in LIVING:
            i=IDX[s]; G[i,i]=-G[i].sum()
        for a in ABSORB: G[IDX[a],IDX[a]]=0
        out.append({"year":year,"sex":sex,"age":age,"matrix":G.tolist()})
    t=SemanticType("GeneratorMatrix",frozenset({"year","sex","age"}),"1/year",death.type.age_scheme,death.type.universe,"Period",join_quality(death.type,transitions.type))
    return SemanticFrame("generator",t,out,death.provenance+transitions.provenance,death.assumptions+transitions.assumptions)

def transition_probabilities(generator: SemanticFrame, interval_years: float=5.0) -> SemanticFrame:
    require_kind(generator.type,"GeneratorMatrix","transition_probabilities")
    out=[]
    for r in generator.rows:
        P=expm(np.asarray(r['matrix'],dtype=float)*interval_years)
        out.append({**{k:r[k] for k in ('year','sex','age')},"matrix":P.tolist()})
    t=SemanticType("TransitionMatrix",generator.type.dims,"probability",generator.type.age_scheme,generator.type.universe,"Interval",generator.type.quality,
                   note=f"P=expm(G*{interval_years:g})")
    return SemanticFrame("probabilities",t,out,generator.provenance,generator.assumptions)

def multistate_life_table(probabilities: SemanticFrame, start_age: int=15, initial_state: str="S", radix: float=100000, max_age: int=120) -> SemanticFrame:
    require_kind(probabilities.type,"TransitionMatrix","multistate_life_table")
    mats={r['age']:np.asarray(r['matrix'],dtype=float) for r in probabilities.rows}
    x=np.zeros(8); x[IDX[initial_state]]=radix
    out=[]; age=start_age; openP=mats.get("80+")
    while age<max_age and x[:4].sum()>1e-6:
        band="80+" if age>=80 else f"{age}-{age+4}"
        P=mats.get(band,openP if age>=80 else None)
        if P is None: break
        before=x.copy(); after=before@P
        deaths=after[4:]-before[4:]
        out.append({"age_start":age,"age_band":band,
                    **{f"live_{s}":before[IDX[s]] for s in LIVING},
                    **{f"death_{s}":max(0.0,deaths[i]) for i,s in enumerate(LIVING)},
                    "alive_total":before[:4].sum(),"dead_total":before[4:].sum()})
        x=after; age+=5
    t=SemanticType("MultiStateLifeTable",frozenset({"age","state"}),"persons",probabilities.type.age_scheme,probabilities.type.universe,"SyntheticCohort",probabilities.type.quality)
    return SemanticFrame("life_table",t,out,probabilities.provenance,probabilities.assumptions + [f"radix={radix:g}; initial state={initial_state}; 80+ hazards held constant through {max_age}"])

def indicators(life_table: SemanticFrame) -> SemanticFrame:
    require_kind(life_table.type,"MultiStateLifeTable","indicators")
    sums={s:0.0 for s in LIVING}; ages={s:0.0 for s in LIVING}
    for r in life_table.rows:
        mid=r['age_start']+2.5
        for s in LIVING:
            d=r[f'death_{s}']; sums[s]+=d; ages[s]+=d*mid
    out=[]
    for s in LIVING:
        out.append({"indicator":"MeanAgeAtDeath","state":s,"value":ages[s]/sums[s] if sums[s] else None,"unit":"years"})
    non=sum(sums[s] for s in ['M','W','V']); nonage=sum(ages[s] for s in ['M','W','V'])
    out.append({"indicator":"MeanAgeAtDeath","state":"NON_S","value":nonage/non if non else None,"unit":"years"})
    out.append({"indicator":"DeathShare","state":"S","value":sums['S']/sum(sums.values()) if sum(sums.values()) else None,"unit":"proportion"})
    t=SemanticType("LifeCourseIndicator",frozenset({"indicator","state"}),"mixed",life_table.type.age_scheme,life_table.type.universe,"SyntheticCohort",life_table.type.quality)
    return SemanticFrame("indicators",t,out,life_table.provenance,life_table.assumptions)

OPS={
    "observed_share": observed_share,
    "extrapolate_share": extrapolate_share,
    "partition_exposure": partition_exposure,
    "death_hazard": death_hazard,
    "transition_hazards": transition_hazards,
    "generator_matrix": generator_matrix,
    "transition_probabilities": transition_probabilities,
    "multistate_life_table": multistate_life_table,
    "indicators": indicators,
}
