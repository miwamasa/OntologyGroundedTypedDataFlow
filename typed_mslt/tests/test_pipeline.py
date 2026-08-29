from mslt.engine import Engine

def test_end_to_end_2024():
    e=Engine('/mnt/data/typed_mslt/examples/male_2024.mslt','/mnt/data')
    env=e.run()
    ind={r['state']:r['value'] for r in env['indicators'].rows if r['indicator']=='MeanAgeAtDeath'}
    assert 73 < ind['S'] < 78
    assert 80 < ind['M'] < 85
    assert ind['M'] > ind['S']
    assert env['indicators'].type.quality.value=='Estimated'

def test_end_to_end_2020_validation_range():
    e=Engine('/mnt/data/typed_mslt/examples/male_2020_validate.mslt','/mnt/data')
    env=e.run()
    ind={r['state']:r['value'] for r in env['indicators'].rows if r['indicator']=='MeanAgeAtDeath'}
    assert abs(ind['M']-82.05) < 1.0
    assert abs(ind['W']-90.72) < 1.0
