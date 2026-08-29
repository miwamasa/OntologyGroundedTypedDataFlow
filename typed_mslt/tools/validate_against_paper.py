import csv, json, sys
from pathlib import Path

paper={"S":75.80,"M":82.05,"W":90.72,"V":74.81,"NON_S":82.91}
p=Path(sys.argv[1] if len(sys.argv)>1 else 'outputs/2020/indicators.csv')
with open(p,encoding='utf-8-sig') as f:
    rows=list(csv.DictReader(f))
calc={r['state']:float(r['value']) for r in rows if r['indicator']=='MeanAgeAtDeath'}
report={k:{"paper_2020":v,"implementation":calc.get(k),"delta":None if k not in calc else calc[k]-v} for k,v in paper.items()}
print(json.dumps(report,ensure_ascii=False,indent=2))
