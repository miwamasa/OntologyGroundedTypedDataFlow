from __future__ import annotations
import csv, re
from pathlib import Path

STATES_JA = {"未婚":"S", "有配偶":"M", "死別":"W", "離別":"V"}
SEX_JA = {"男":"male", "女":"female", "夫":"male", "妻":"female"}
CANON_BANDS = ["15-19","20-24","25-29","30-34","35-39","40-44","45-49","50-54","55-59","60-64","65-69","70-74","75-79","80+"]

def read_cp932(path):
    with open(path, encoding="cp932", newline="") as f:
        return list(csv.reader(f))

def number(x):
    if x is None: return 0.0
    s = str(x).strip().replace(",", "")
    if s in {"", "-", "***", "…", "・"}: return 0.0
    try: return float(s)
    except ValueError: return 0.0

def norm_year(x):
    m = re.search(r"(\d{4})", str(x))
    return int(m.group(1)) if m else None

def age_band_from_label(label: str) -> str | None:
    s = str(label).replace("～","-").replace("歳","").replace("以上","+").replace("以下","")
    if "総数" in s or "不詳" in s or "再掲" in s: return None
    if s in {"19", "19+"}: return "15-19"
    m = re.search(r"(\d+)-(\d+)", s)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        if lo >= 80: return "80+"
        if hi < 15: return None
        return f"{lo}-{hi}"
    m = re.search(r"(\d+)\+", s)
    if m:
        return "80+" if int(m.group(1)) >= 80 else f"{int(m.group(1))}+"
    m = re.search(r"(?:夫_|妻_|死亡者_|配偶者_)?(\d+)$", s)
    if m:
        a = int(m.group(1))
        if a < 15: return None
        if a >= 80: return "80+"
        lo = (a//5)*5
        if lo < 15: lo=15
        return f"{lo}-{lo+4}"
    if "80" in s: return "80+"
    if "85" in s or "90" in s or "95" in s or "100" in s: return "80+"
    return None

def band_midpoint(band: str) -> float:
    if band == "80+": return 82.5
    lo, hi = map(int, band.split("-"))
    return (lo+hi)/2

def band_start(band: str) -> int:
    return 80 if band == "80+" else int(band.split("-")[0])
