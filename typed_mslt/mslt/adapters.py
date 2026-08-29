from __future__ import annotations
from collections import defaultdict
from pathlib import Path
import re
from .frame import SemanticFrame
from .types import SemanticType, Quality
from .utils import read_cp932, number, norm_year, age_band_from_label, CANON_BANDS, STATES_JA, SEX_JA

AGE_SCHEME="5y_80plus"
DIMS=frozenset({"year","sex","age","state"})
TDIMS=frozenset({"year","sex","age","from_state","to_state"})

# --------------------------------------------------------------------------
# Type-level signatures. A source's semantic type depends on which table it
# reads and the arguments given, never on the file's contents, so these can be
# evaluated with no data present. Each adapter below asks its own signature for
# the type it returns, so `mslt check` and `mslt run` cannot drift apart.
#
# An occurrence-exposure numerator counts the persons who experienced the
# event, so transition counts are measured in `person`, the same dimension as a
# death count. That is what makes both hazard paths derive to 1/year.
# --------------------------------------------------------------------------

def ty_estat_death(path=None) -> SemanticType:
    return SemanticType("DeathCount",DIMS,"person",AGE_SCHEME,quality=Quality.OBSERVED)

def ty_estat_census5(path=None) -> SemanticType:
    return SemanticType("MaritalPopulation",DIMS,"person",AGE_SCHEME,time_semantics="CensusPoint",
                        quality=Quality.OBSERVED,note="2015/2020: 不詳補完値 preferred when available")

def ty_estat_marriage3(path=None, kind: str="first") -> SemanticType:
    return SemanticType("TransitionCount",TDIMS,"person",AGE_SCHEME,quality=Quality.OBSERVED,
                        source_state="S" if kind=="first" else None,target_state="M")

def ty_estat_divorce3(path=None) -> SemanticType:
    return SemanticType("TransitionCount",TDIMS,"person",AGE_SCHEME,quality=Quality.OBSERVED,
                        source_state="M",target_state="V")

def ty_estat_spousal_death(path=None) -> SemanticType:
    return SemanticType("TransitionCount",TDIMS,"person",AGE_SCHEME,quality=Quality.OBSERVED,
                        source_state="M",target_state="W")

def ty_estat_remarriage7(path=None, prior: str="死別", tail_years: float=12.0) -> SemanticType:
    return SemanticType("TransitionCount",TDIMS,"person",AGE_SCHEME,quality=Quality.ESTIMATED,
                        source_state="W" if prior=="死別" else "V",target_state="M",
                        note="current remarriage age derived from dissolution age + elapsed years")

def ty_jmd5(path=None) -> SemanticType:
    return SemanticType("Exposure",frozenset({"year","sex","age"}),"person-year",AGE_SCHEME,
                        quality=Quality.OBSERVED)

def estat_death(path: str) -> SemanticFrame:
    rows=read_cp932(path); h=rows[12]; out=[]
    for r in rows[13:]:
        if len(r)<16: continue
        year=norm_year(r[5]); band=age_band_from_label(r[8])
        if not year or not band: continue
        # male columns 12-15; female columns 18-21 in this table
        for sex, cols in [("male", {"M":12,"S":13,"W":14,"V":15}), ("female", {"M":18,"S":19,"W":20,"V":21})]:
            for st,c in cols.items():
                if c < len(r): out.append({"year":year,"sex":sex,"age":band,"state":st,"value":number(r[c])})
    # aggregate 80+ from all high-age rows
    agg=defaultdict(float)
    for x in out: agg[(x["year"],x["sex"],x["age"],x["state"])]+=x["value"]
    out=[{"year":y,"sex":s,"age":a,"state":st,"value":v} for (y,s,a,st),v in agg.items()]
    return SemanticFrame("deaths",ty_estat_death(),out,[str(path),"e-Stat mortality table 7"])

def estat_census5(path: str) -> SemanticFrame:
    rows=read_cp932(path); candidates={}
    # 2015/2020 contain both original and "不詳補完値" series. Prefer the complemented series,
    # matching the methodology used in the cited multistate-life-table paper.
    for r in rows[14:]:
        if len(r)<19: continue
        year=norm_year(r[2]); sex=SEX_JA.get(r[5]); label=r[8]
        if not year or not sex: continue
        band=age_band_from_label(label)
        if band is None: continue
        priority=1 if "不詳補完値" in r[2] else 0
        vals={"S":number(r[11]),"M":number(r[12]),"W":number(r[13]),"V":number(r[14])}
        for st,v in vals.items():
            k=(year,sex,band,st)
            if k not in candidates or priority>candidates[k][0]: candidates[k]=(priority,v)
            elif priority==candidates[k][0]: candidates[k]=(priority,candidates[k][1]+v)
    out=[{"year":y,"sex":s,"age":a,"state":st,"value":pv[1]} for (y,s,a,st),pv in candidates.items()]
    return SemanticFrame("census",ty_estat_census5(),out,[str(path),"e-Stat census marital-status time series; complemented values preferred"])

def estat_marriage3(path: str, kind: str="first") -> SemanticFrame:
    rows=read_cp932(path); out=[]
    wanted="初婚" if kind=="first" else "再婚"
    for r in rows[13:]:
        if len(r)<17 or r[8]!=wanted: continue
        year=norm_year(r[5]); sex=SEX_JA.get(r[11]); band=age_band_from_label(r[14])
        if not year or not sex or not band: continue
        out.append({"year":year,"sex":sex,"age":band,"from_state":"S" if kind=="first" else "?","to_state":"M","value":number(r[16])})
    agg=defaultdict(float)
    for x in out: agg[(x["year"],x["sex"],x["age"],x["from_state"],x["to_state"])]+=x["value"]
    out=[{"year":y,"sex":s,"age":a,"from_state":f,"to_state":to,"value":v} for (y,s,a,f,to),v in agg.items()]
    return SemanticFrame(kind,ty_estat_marriage3(kind=kind),out,[str(path),f"e-Stat marriage table 3 ({wanted})"])

def estat_divorce3(path: str) -> SemanticFrame:
    rows=read_cp932(path); header=rows[12]; out=[]
    # female: row totals by wife's age; male: total row, columns by husband's age
    # male column labels are header[10:]
    for r in rows[13:]:
        if len(r)<11: continue
        year=norm_year(r[5]);
        if not year: continue
        wife_band=age_band_from_label(r[8])
        if wife_band:
            out.append({"year":year,"sex":"female","age":wife_band,"from_state":"M","to_state":"V","value":number(r[10])})
        if r[8]=="妻_総数":
            for j in range(11,len(r)):
                band=age_band_from_label(header[j] if j<len(header) else "")
                if band:
                    out.append({"year":year,"sex":"male","age":band,"from_state":"M","to_state":"V","value":number(r[j])})
    agg=defaultdict(float)
    for x in out: agg[(x["year"],x["sex"],x["age"],"M","V")]+=x["value"]
    out=[{"year":y,"sex":s,"age":a,"from_state":"M","to_state":"V","value":v} for (y,s,a,_,_),v in agg.items()]
    return SemanticFrame("divorce",ty_estat_divorce3(),out,[str(path),"e-Stat divorce table 3"])

def estat_spousal_death(path: str) -> SemanticFrame:
    rows=read_cp932(path); header=rows[12]; out=[]
    # Surviving spouse transitions M->W. Deceased male -> surviving female, deceased female -> surviving male.
    for r in rows[13:]:
        if len(r)<14: continue
        year=norm_year(r[5]); deceased=SEX_JA.get(r[8]);
        if not year or deceased not in {"male","female"}: continue
        surviving="female" if deceased=="male" else "male"
        # only total deceased-age row so every spouse is counted once
        if r[11] != "死亡者_総数": continue
        for j in range(14,len(r)):
            band=age_band_from_label(header[j] if j<len(header) else "")
            if band:
                out.append({"year":year,"sex":surviving,"age":band,"from_state":"M","to_state":"W","value":number(r[j])})
    agg=defaultdict(float)
    for x in out: agg[(x["year"],x["sex"],x["age"],"M","W")]+=x["value"]
    out=[{"year":y,"sex":s,"age":a,"from_state":"M","to_state":"W","value":v} for (y,s,a,_,_),v in agg.items()]
    return SemanticFrame("widowhood",ty_estat_spousal_death(),out,[str(path),"e-Stat stored mortality table 1; spouse-age margin"])

def estat_remarriage7(path: str, prior: str, tail_years: float=12.0) -> SemanticFrame:
    rows=read_cp932(path); out=[]
    src="W" if prior=="死別" else "V"
    # Cell semantics: age at previous dissolution + years since dissolution -> estimated age at remarriage.
    for r in rows[13:]:
        if len(r)<30 or r[11]!=prior: continue
        year=norm_year(r[8]); sex=SEX_JA.get(r[5]);
        if not year or not sex: continue
        m=re.search(r"(\d+)歳",r[14])
        if not m: continue
        dissolution_age=int(m.group(1))
        for j in range(17,29):
            if j==28: elapsed=tail_years
            else: elapsed=j-17
            remarriage_age=int(round(dissolution_age+elapsed))
            band="80+" if remarriage_age>=80 else (f"{max(15,(remarriage_age//5)*5)}-{max(15,(remarriage_age//5)*5)+4}")
            if band not in CANON_BANDS: continue
            out.append({"year":year,"sex":sex,"age":band,"from_state":src,"to_state":"M","value":number(r[j])})
    agg=defaultdict(float)
    for x in out: agg[(x["year"],x["sex"],x["age"],src,"M")]+=x["value"]
    out=[{"year":y,"sex":s,"age":a,"from_state":src,"to_state":"M","value":v} for (y,s,a,_,_),v in agg.items()]
    return SemanticFrame(f"remarriage_{src}",ty_estat_remarriage7(prior=prior,tail_years=tail_years),out,[str(path),f"e-Stat marriage table 7 ({prior})"],
                         [f"11+ years since dissolution represented by {tail_years:g} years"])

def jmd5(path: str) -> SemanticFrame:
    out=[]
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line=line.strip()
        if not line or line.startswith("#") or line.startswith("Year") or line.startswith("Japan") or line.startswith("Year"): continue
        parts=line.split()
        if len(parts)<5 or not parts[0].isdigit(): continue
        year=int(parts[0]); age=parts[1]
        female=float(parts[2]); male=float(parts[3])
        band=age_band_from_label(age)
        if band is None: continue
        out += [
            {"year":year,"sex":"female","age":band,"value":female},
            {"year":year,"sex":"male","age":band,"value":male},
        ]
    agg=defaultdict(float)
    for x in out: agg[(x["year"],x["sex"],x["age"])]+=x["value"]
    out=[{"year":y,"sex":s,"age":a,"value":v} for (y,s,a),v in agg.items()]
    return SemanticFrame("jmd",ty_jmd5(),out,[str(path),"JMD/IPSS exposure-to-risk, 5x1"])

ADAPTER_TYPES={
    "estat_death": ty_estat_death,
    "estat_census5": ty_estat_census5,
    "estat_marriage3": ty_estat_marriage3,
    "estat_divorce3": ty_estat_divorce3,
    "estat_spousal_death": ty_estat_spousal_death,
    "estat_remarriage7": ty_estat_remarriage7,
    "jmd5": ty_jmd5,
}

ADAPTERS={
    "estat_death": estat_death,
    "estat_census5": estat_census5,
    "estat_marriage3": estat_marriage3,
    "estat_divorce3": estat_divorce3,
    "estat_spousal_death": estat_spousal_death,
    "estat_remarriage7": estat_remarriage7,
    "jmd5": jmd5,
}
