"""Typed transformations and the Markov multistate life table.

Each operation is split in two: a *signature* (``sig_*``) that maps input
semantic types to the output semantic type, and the transformation itself,
which computes rows and asks its own signature for the type it returns.

Keeping one definition of each typing rule is what lets ``mslt check`` derive
every type without opening a CSV while guaranteeing it cannot disagree with
what ``mslt run`` actually produces.

Operations that depend on the model's shape take an ``ontology`` keyword: the
set of living states, the sparsity pattern of the generator, and the size of
G(x) are all read off the ontology rather than written into this module. The
engine supplies it, so a program needs no change to be run against a different
ontology.
"""
from __future__ import annotations
from collections import defaultdict
import numpy as np
from scipy.linalg import expm
from .frame import SemanticFrame
from .ontology import Ontology
from .types import (
    SemanticType, SemanticTypeError, Quality, require_kind, require_dims, require_same_universe,
    require_unit, require_dimensionless, divide_units, multiply_units, join_quality,
)
from .units import PERSON, YEAR, PERSON_YEAR, PER_YEAR, MIXED
from .utils import CANON_BANDS

HAZARD_DIMS=frozenset({"year","sex","age","from_state","to_state"})

def _lookup(frame, *, year, sex):
    return [r for r in frame.rows if r.get("year")==year and r.get("sex")==sex]

# --------------------------------------------------------------------------
# observed_share / extrapolate_share
# --------------------------------------------------------------------------

def _share_unit(census: SemanticType, op: str):
    # A share is a population divided by a population: dimensionless by
    # construction, and only then named "proportion".
    return divide_units(census.unit, census.unit, op).labeled("proportion")

def sig_observed_share(census: SemanticType, year: int, sex: str) -> SemanticType:
    op="observed_share"
    require_kind(census,"MaritalPopulation",op)
    require_dims(census,{"age","state"},op)
    require_unit(census.unit,PERSON,op,"a marital-status population")
    return SemanticType("MaritalShare",census.dims,_share_unit(census,op),census.age_scheme,
                        census.universe,"Period",Quality.OBSERVED)

def observed_share(census: SemanticFrame, year: int, sex: str, *, ontology: Ontology) -> SemanticFrame:
    t=sig_observed_share(census.type,year,sex)
    living=ontology.living_states
    pop=defaultdict(float)
    for r in _lookup(census,year=year,sex=sex): pop[(r["age"],r["state"])]+=r["value"]
    out=[]
    for age in CANON_BANDS:
        den=sum(pop[(age,s)] for s in living)
        if den<=0: continue
        for s in living: out.append({"year":year,"sex":sex,"age":age,"state":s,"value":pop[(age,s)]/den})
    return SemanticFrame(f"share_{year}",t,out,census.provenance+ [f"observed marital shares for {year}"])

def sig_extrapolate_share(census: SemanticType, base_years: list[int], target_year: int, sex: str) -> SemanticType:
    op="extrapolate_share"
    require_kind(census,"MaritalPopulation",op)
    require_dims(census,{"age","state"},op)
    require_unit(census.unit,PERSON,op,"a marital-status population")
    if len(base_years)!=2:
        raise ValueError(f"{op}: expected exactly two base years, got {base_years}")
    y0,y1=base_years
    return SemanticType("MaritalShare",census.dims,_share_unit(census,op),census.age_scheme,
                        census.universe,"Period",Quality.ESTIMATED,
                        note=f"linear extrapolation {y0}->{y1}->{target_year}")

def extrapolate_share(census: SemanticFrame, base_years: list[int], target_year: int, sex: str,
                      *, ontology: Ontology) -> SemanticFrame:
    t=sig_extrapolate_share(census.type,base_years,target_year,sex)
    living=ontology.living_states
    y0,y1=base_years
    s0=observed_share(census,y0,sex,ontology=ontology); s1=observed_share(census,y1,sex,ontology=ontology)
    d0={(r['age'],r['state']):r['value'] for r in s0.rows}; d1={(r['age'],r['state']):r['value'] for r in s1.rows}
    factor=(target_year-y1)/(y1-y0)
    out=[]
    for age in CANON_BANDS:
        raw={s:max(0.0,d1.get((age,s),0)+factor*(d1.get((age,s),0)-d0.get((age,s),0))) for s in living}
        z=sum(raw.values())
        if z<=0: continue
        for s in living: out.append({"year":target_year,"sex":sex,"age":age,"state":s,"value":raw[s]/z})
    return SemanticFrame(f"share_{target_year}",t,out,census.provenance,
                         [f"linear extrapolation of marital shares from {y0},{y1} to {target_year}; clipped at zero and renormalized"])

# --------------------------------------------------------------------------
# partition_exposure
# --------------------------------------------------------------------------

def sig_partition_exposure(exposure: SemanticType, share: SemanticType, year: int, sex: str) -> SemanticType:
    op="partition_exposure"
    require_kind(exposure,"Exposure",op); require_kind(share,"MaritalShare",op)
    require_same_universe(exposure,share,op)
    require_dims(exposure,{"year","sex","age"},op); require_dims(share,{"age","state"},op)
    # Exposure must be a person-year, not a head count: dividing a death count
    # by a head count yields a dimensionless ratio, not a rate.
    require_unit(exposure.unit,PERSON_YEAR,op,"exposure-to-risk")
    require_dimensionless(share.unit,op,"a marital-status share")
    unit=multiply_units(exposure.unit,share.unit,op)
    return SemanticType("StateExposure",frozenset({"year","sex","age","state"}),unit,exposure.age_scheme,
                        exposure.universe,"Period",join_quality(exposure,share))

def partition_exposure(exposure: SemanticFrame, share: SemanticFrame, year: int, sex: str) -> SemanticFrame:
    t=sig_partition_exposure(exposure.type,share.type,year,sex)
    e={(r['age']):r['value'] for r in _lookup(exposure,year=year,sex=sex)}
    out=[]
    for r in _lookup(share,year=year,sex=sex):
        if r['age'] in e: out.append({**r,"value":r['value']*e[r['age']]})
    return SemanticFrame("state_exposure",t,out,exposure.provenance+share.provenance,share.assumptions)

# --------------------------------------------------------------------------
# hazards
# --------------------------------------------------------------------------

def _occurrence_exposure_unit(numerator: SemanticType, state_exposure: SemanticType, op: str, what: str):
    """Derive an occurrence-exposure rate's unit and check it came out as 1/year."""
    require_unit(state_exposure.unit,PERSON_YEAR,op,"state-specific exposure")
    unit=divide_units(numerator.unit,state_exposure.unit,op)
    require_unit(unit,PER_YEAR,op,f"a hazard derived from {what}")
    return unit

def sig_death_hazard(deaths: SemanticType, state_exposure: SemanticType, year: int, sex: str) -> SemanticType:
    op="death_hazard"
    require_kind(deaths,"DeathCount",op); require_kind(state_exposure,"StateExposure",op)
    require_same_universe(deaths,state_exposure,op)
    require_dims(deaths,{"age","state"},op); require_dims(state_exposure,{"age","state"},op)
    unit=_occurrence_exposure_unit(deaths,state_exposure,op,"a death count")
    return SemanticType("HazardRate",HAZARD_DIMS,unit,deaths.age_scheme,deaths.universe,"Period",
                        join_quality(deaths,state_exposure),target_state="D")

def death_hazard(deaths: SemanticFrame, state_exposure: SemanticFrame, year: int, sex: str,
                 *, ontology: Ontology) -> SemanticFrame:
    t=sig_death_hazard(deaths.type,state_exposure.type,year,sex)
    absorbing=ontology.absorbing
    d=defaultdict(float); e=defaultdict(float)
    for r in _lookup(deaths,year=year,sex=sex): d[(r['age'],r['state'])]+=r['value']
    for r in _lookup(state_exposure,year=year,sex=sex): e[(r['age'],r['state'])]+=r['value']
    out=[]
    for age in CANON_BANDS:
        for s in ontology.living_states:
            den=e[(age,s)]; val=d[(age,s)]/den if den>0 else 0.0
            out.append({"year":year,"sex":sex,"age":age,"from_state":s,"to_state":absorbing,"value":val})
    return SemanticFrame("death_hazard",t,out,deaths.provenance+state_exposure.provenance,state_exposure.assumptions)

def sig_transition_hazards(frames: list[SemanticType], state_exposure: SemanticType, year: int, sex: str,
                           *, ontology: Ontology) -> SemanticType:
    op="transition_hazards"
    require_kind(state_exposure,"StateExposure",op)
    require_dims(state_exposure,{"age","state"},op)
    for f in frames:
        require_kind(f,"TransitionCount",op)
        require_dims(f,{"age","from_state","to_state"},op)
        require_same_universe(f,state_exposure,op)
        _occurrence_exposure_unit(f,state_exposure,op,"a transition count")
        # A hazard may only be built for a transition the ontology licenses,
        # so an unlicensed edge is rejected before any data is read.
        if f.source_state and f.target_state and not ontology.is_licensed(f.source_state,f.target_state):
            raise SemanticTypeError(
                f"{op}: transition {f.source_state}->{f.target_state} is not licensed by "
                f"ontology {ontology.name!r}"
            )
    return SemanticType("HazardRate",HAZARD_DIMS,PER_YEAR,state_exposure.age_scheme,
                        state_exposure.universe,"Period",join_quality(state_exposure,*frames))

def transition_hazards(frames: list[SemanticFrame], state_exposure: SemanticFrame, year: int, sex: str,
                       *, ontology: Ontology) -> SemanticFrame:
    t=sig_transition_hazards([f.type for f in frames],state_exposure.type,year,sex,ontology=ontology)
    e={(r['age'],r['state']):r['value'] for r in _lookup(state_exposure,year=year,sex=sex)}
    out=[]; prov=list(state_exposure.provenance); assumptions=list(state_exposure.assumptions)
    for f in frames:
        prov += f.provenance; assumptions += f.assumptions
        agg=defaultdict(float)
        for r in _lookup(f,year=year,sex=sex): agg[(r['age'],r['from_state'],r['to_state'])]+=r['value']
        for (age,src,dst),num in agg.items():
            den=e.get((age,src),0.0)
            out.append({"year":year,"sex":sex,"age":age,"from_state":src,"to_state":dst,"value":num/den if den>0 else 0.0})
    return SemanticFrame("transition_hazard",t,out,prov,assumptions)

# --------------------------------------------------------------------------
# generator / probabilities
# --------------------------------------------------------------------------

def sig_generator_matrix(death: SemanticType, transitions: SemanticType, year: int, sex: str) -> SemanticType:
    op="generator_matrix"
    require_kind(death,"HazardRate",op); require_kind(transitions,"HazardRate",op)
    require_same_universe(death,transitions,op)
    require_dims(death,{"age","from_state","to_state"},op)
    require_dims(transitions,{"age","from_state","to_state"},op)
    require_unit(death.unit,PER_YEAR,op,"a death hazard")
    require_unit(transitions.unit,PER_YEAR,op,"a social-transition hazard")
    return SemanticType("GeneratorMatrix",frozenset({"year","sex","age"}),death.unit,death.age_scheme,
                        death.universe,"Period",join_quality(death,transitions))

def generator_matrix(death: SemanticFrame, transitions: SemanticFrame, year: int, sex: str,
                     *, ontology: Ontology) -> SemanticFrame:
    t=sig_generator_matrix(death.type,transitions.type,year,sex)
    space=ontology.state_space; idx=space.index; n=space.size
    by_age={a:np.zeros((n,n),dtype=float) for a in CANON_BANDS}
    for f in [transitions,death]:
        for r in _lookup(f,year=year,sex=sex):
            age,src,dst,val=r['age'],r['from_state'],r['to_state'],max(0.0,float(r['value']))
            if age not in by_age: continue
            if src not in space.living:
                raise SemanticTypeError(
                    f"generator_matrix: {src!r} is not a living state of ontology {ontology.name!r}")
            if not ontology.is_licensed(src,dst):
                raise SemanticTypeError(
                    f"generator_matrix: transition {src}->{dst} is not licensed by "
                    f"ontology {ontology.name!r}")
            # Death is recorded in the absorbing state that remembers where the
            # cohort member died, so mean age at death stays attributable.
            target=space.absorbed_from(src) if dst==ontology.absorbing else dst
            by_age[age][idx[src],idx[target]]+=val
    out=[]
    for age,G in by_age.items():
        for s in space.living:
            i=idx[s]; G[i,i]=-G[i].sum()
        for a in space.absorbed: G[idx[a],idx[a]]=0
        out.append({"year":year,"sex":sex,"age":age,"matrix":G.tolist()})
    return SemanticFrame("generator",t,out,death.provenance+transitions.provenance,death.assumptions+transitions.assumptions)

def sig_transition_probabilities(generator: SemanticType, interval_years: float=5.0) -> SemanticType:
    op="transition_probabilities"
    require_kind(generator,"GeneratorMatrix",op)
    # expm(G*t) is only defined when G*t is dimensionless; that is exactly what
    # makes a 1/year generator and a year-valued interval the lawful pairing.
    product=multiply_units(generator.unit,YEAR,op)
    require_dimensionless(product,op,f"G(x) times a {interval_years:g}-year interval")
    return SemanticType("TransitionMatrix",generator.dims,product.labeled("probability"),generator.age_scheme,
                        generator.universe,"Interval",generator.quality,
                        note=f"P=expm(G*{interval_years:g})")

def transition_probabilities(generator: SemanticFrame, interval_years: float=5.0) -> SemanticFrame:
    t=sig_transition_probabilities(generator.type,interval_years)
    out=[]
    for r in generator.rows:
        P=expm(np.asarray(r['matrix'],dtype=float)*interval_years)
        out.append({**{k:r[k] for k in ('year','sex','age')},"matrix":P.tolist()})
    return SemanticFrame("probabilities",t,out,generator.provenance,generator.assumptions)

# --------------------------------------------------------------------------
# life table / indicators
# --------------------------------------------------------------------------

def sig_multistate_life_table(probabilities: SemanticType, start_age: int=15, initial_state: str="S",
                              radix: float=100000, max_age: int=120, *, ontology: Ontology) -> SemanticType:
    op="multistate_life_table"
    require_kind(probabilities,"TransitionMatrix",op)
    require_dims(probabilities,{"age"},op)
    require_dimensionless(probabilities.unit,op,"a transition probability")
    if probabilities.time_semantics!="Interval":
        raise SemanticTypeError(
            f"{op}: expected Interval time semantics, got {probabilities.time_semantics}; "
            "a synthetic cohort may only be propagated by interval transition probabilities"
        )
    if initial_state not in ontology.living_states:
        raise SemanticTypeError(
            f"{op}: initial state {initial_state!r} is not a living state of "
            f"ontology {ontology.name!r} {list(ontology.living_states)}"
        )
    return SemanticType("MultiStateLifeTable",frozenset({"age","state"}),PERSON,probabilities.age_scheme,
                        probabilities.universe,"SyntheticCohort",probabilities.quality)

def multistate_life_table(probabilities: SemanticFrame, start_age: int=15, initial_state: str="S",
                          radix: float=100000, max_age: int=120, *, ontology: Ontology) -> SemanticFrame:
    t=sig_multistate_life_table(probabilities.type,start_age,initial_state,radix,max_age,ontology=ontology)
    space=ontology.state_space; n=space.n_living
    mats={r['age']:np.asarray(r['matrix'],dtype=float) for r in probabilities.rows}
    x=np.zeros(space.size); x[space.index[initial_state]]=radix
    out=[]; age=start_age; openP=mats.get("80+")
    while age<max_age and x[:n].sum()>1e-6:
        band="80+" if age>=80 else f"{age}-{age+4}"
        P=mats.get(band,openP if age>=80 else None)
        if P is None: break
        before=x.copy(); after=before@P
        deaths=after[n:]-before[n:]
        out.append({"age_start":age,"age_band":band,
                    **{f"live_{s}":before[space.index[s]] for s in space.living},
                    **{f"death_{s}":max(0.0,deaths[i]) for i,s in enumerate(space.living)},
                    "alive_total":before[:n].sum(),"dead_total":before[n:].sum()})
        x=after; age+=5
    return SemanticFrame("life_table",t,out,probabilities.provenance,probabilities.assumptions + [f"radix={radix:g}; initial state={initial_state}; 80+ hazards held constant through {max_age}"])

def sig_indicators(life_table: SemanticType) -> SemanticType:
    op="indicators"
    require_kind(life_table,"MultiStateLifeTable",op)
    require_dims(life_table,{"age","state"},op)
    return SemanticType("LifeCourseIndicator",frozenset({"indicator","state"}),MIXED,life_table.age_scheme,
                        life_table.universe,"SyntheticCohort",life_table.quality)

def indicators(life_table: SemanticFrame, *, ontology: Ontology) -> SemanticFrame:
    t=sig_indicators(life_table.type)
    living=ontology.living_states; ref=ontology.reference_state
    sums={s:0.0 for s in living}; ages={s:0.0 for s in living}
    for r in life_table.rows:
        mid=r['age_start']+2.5
        for s in living:
            d=r[f'death_{s}']; sums[s]+=d; ages[s]+=d*mid
    out=[]
    for s in living:
        out.append({"indicator":"MeanAgeAtDeath","state":s,"value":ages[s]/sums[s] if sums[s] else None,"unit":"years"})
    others=[s for s in living if s!=ref]
    non=sum(sums[s] for s in others); nonage=sum(ages[s] for s in others)
    out.append({"indicator":"MeanAgeAtDeath","state":f"NON_{ref}","value":nonage/non if non else None,"unit":"years"})
    total=sum(sums.values())
    out.append({"indicator":"DeathShare","state":ref,"value":sums[ref]/total if total else None,"unit":"proportion"})
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

# Type-level counterparts, keyed identically. ``mslt check`` evaluates the
# pipeline in this interpretation alone, so it needs no data files at all.
TYPE_OPS={
    "observed_share": sig_observed_share,
    "extrapolate_share": sig_extrapolate_share,
    "partition_exposure": sig_partition_exposure,
    "death_hazard": sig_death_hazard,
    "transition_hazards": sig_transition_hazards,
    "generator_matrix": sig_generator_matrix,
    "transition_probabilities": sig_transition_probabilities,
    "multistate_life_table": sig_multistate_life_table,
    "indicators": sig_indicators,
}
