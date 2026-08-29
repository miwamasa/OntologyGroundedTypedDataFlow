from pathlib import Path
from mslt.adapters import estat_death, estat_census5

DATA_DIR = Path(__file__).resolve().parent.parent / 'data' / 'input_csv'

def test_death_2024_male_total_states():
    f=estat_death(str(DATA_DIR / 'FEH_00450011_260828095117.csv'))
    rows=[r for r in f.rows if r['year']==2024 and r['sex']=='male']
    assert any(r['age']=='15-19' and r['state']=='S' and r['value']==714 for r in rows)
    # canonical open band exists after aggregation
    assert any(r['age']=='80+' and r['state']=='M' for r in rows)

def test_census_2020_male_60_64():
    f=estat_census5(str(DATA_DIR / 'FEH_00200521_260828100536.csv'))
    d={(r['year'],r['sex'],r['age'],r['state']):r['value'] for r in f.rows}
    assert d[(2020,'male','60-64','S')]==636443
    assert d[(2020,'male','60-64','M')]==2664017
