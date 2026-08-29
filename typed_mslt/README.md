# typed-mslt

人口動態統計・国勢調査・JMD を、**オントロジーで意味付けした型付きデータフロー**として合成し、婚姻状態の多相生命表を生成する実装です。

単なる CSV ETL ではなく、各中間データに `DeathCount`、`StateExposure`、`TransitionCount<S->M>`、`HazardRate<M->W>` などの意味型を付けます。推計値は `Estimated<...>` として下流まで伝播します。

## データフロー

```text
CSV / official statistics
  -> semantic adapters
  -> typed observations
  -> marital-status shares
  -> state-specific exposure
  -> death / social transition hazards
  -> age-specific generator G(x)
  -> P(x) = expm(5 G(x))
  -> synthetic cohort propagation
  -> multistate life table
  -> mean age at death by state
```

状態は `S=未婚, M=有配偶, W=死別, V=離別, D=死亡`。許される遷移は `ontology/marital.yaml` で定義します。

このオントロジーは検査表ではなく、**モデルの形そのもの**を決めます。生存状態の集合、死亡を状態別に分割した吸収状態、生成子行列 G(x) の大きさ（8×8）と疎構造は、すべて YAML から導出されます。`transforms.py` に状態名や行列サイズは書かれていません。オントロジーを差し替えれば、同じプログラムが別のモデルになります:

```bash
# 死別・離別を終端状態とする変種では、再婚のハザードがデータを読む前に拒否される
PYTHONPATH=typed_mslt python -m mslt check typed_mslt/examples/male_2024.mslt \
  --ontology typed_mslt/ontology/marital_absorbing_dissolution.yaml
# ERROR: source remarriage_w: transition W->M is not licensed by
#        ontology 'marital_absorbing_dissolution'
```

## DSL

`examples/male_2024.mslt` の主要部分:

```text
source deaths :: DeathCount = estat_death("FEH_00450011_260828095117.csv")
source census :: MaritalPopulation = estat_census5("FEH_00200521_260828100536.csv")
source first_marriage :: TransitionCount = estat_marriage3("婚姻・中巻３...csv", kind="first")
source divorce :: TransitionCount = estat_divorce3("離婚・中巻３...csv")
source widowhood :: TransitionCount = estat_spousal_death("15歳以上有配偶死亡数...csv")
source remarriage_w :: Estimated = estat_remarriage7("婚姻・中巻７...csv", prior="死別")
source remarriage_v :: Estimated = estat_remarriage7("婚姻・中巻７...csv", prior="離別")
source jmd :: Exposure = jmd5("typed_mslt/data/jmd_exposure_5x1_2020_2024.txt")

let share = extrapolate_share(census, base_years=[2015,2020], target_year=2024, sex="male")
let state_exposure = partition_exposure(jmd, share, year=2024, sex="male")
let death_rate = death_hazard(deaths, state_exposure, year=2024, sex="male")
let social_rate = transition_hazards([first_marriage,divorce,widowhood,remarriage_w,remarriage_v], state_exposure, year=2024, sex="male")
let generator = generator_matrix(death_rate, social_rate, year=2024, sex="male")
let probabilities = transition_probabilities(generator, interval_years=5.0)
emit life_table = multistate_life_table(probabilities, start_age=15, initial_state="S", radix=100000, max_age=120)
emit indicators = indicators(life_table)
```

## 実行

元 CSV は `typed_mslt/data/input_csv/` に置きます。リポジトリのルートを `--data-root` として、リポジトリルートから実行します:

```bash
PYTHONPATH=typed_mslt python -m mslt check typed_mslt/examples/male_2024.mslt --data-root .
PYTHONPATH=typed_mslt python -m mslt explain typed_mslt/examples/male_2024.mslt --data-root .
PYTHONPATH=typed_mslt python -m mslt run typed_mslt/examples/male_2024.mslt --data-root . --out typed_mslt/outputs/2024
```

`check` はパイプラインを型の解釈だけで評価するため、CSV を一切読みません（`--data-root` が存在しなくても型の誤りを報告します）。各ノードに導出された意味型を表示します:

```text
  jmd            : Exposure[age,sex,year; 5y_80plus; person-year]
  share          : Estimated<MaritalShare[age,sex,state,year; 5y_80plus; proportion]>
  state_exposure : Estimated<StateExposure[age,sex,state,year; 5y_80plus; person-year]>
  death_rate     : Estimated<HazardRate<?->D>[age,from_state,sex,to_state,year; 5y_80plus; 1/year]>
  ...
```

テスト:

```bash
cd typed_mslt
PYTHONPATH=. pytest -q
```

## 現在の実装結果

公開集計表のみを用いた 5歳階級モデルです。今回の入力ファイルで実行すると、男性の平均死亡年齢（死亡時状態別）は概ね次の値になります。

| 年 | 未婚 S | 有配偶 M | 死別 W | 離別 V | 未婚以外 |
|---|---:|---:|---:|---:|---:|
| 2020 実装 | 77.50 | 82.37 | 90.93 | 75.43 | 83.64 |
| 2024 暫定 | 76.48 | 82.16 | 90.01 | 75.42 | 83.22 |

2020年の石井論文表3の値（未婚75.80、有配偶82.05、死別90.72、離別74.81、未婚以外82.91）との比較では、公開表・5歳階級という制約の下で、有配偶・死別はかなり近い一方、未婚などには差が残ります。

## 仮定の振れ幅

推計値の型は「推計である」という印だけでなく、**依存している名前付き仮定の集合**を持ちます。型が到達可能と判定した仮定だけを振ることで、各指標がどこまで動くかを機械的に出せます:

```bash
PYTHONPATH=typed_mslt python -m mslt sensitivity typed_mslt/examples/male_2024.mslt --data-root .
```

2024年・男性、宣言された3つの仮定を全組み合わせ（36通り）で振った結果:

| 指標 | 下限 | 基準値 | 上限 | 振れ幅 |
|---|---:|---:|---:|---:|
| 未婚 S | 74.44 | 76.48 | 77.40 | 2.96 |
| 有配偶 M | 81.14 | 82.16 | 82.54 | 1.40 |
| 死別 W | 87.78 | 90.01 | 91.02 | 3.23 |
| 離別 V | 74.25 | 75.42 | 75.94 | 1.69 |

仮定ごとの寄与を分けると、次のことが分かります。

- **未婚 S を最も動かすのは配偶状態割合の外挿**（単独で 2.52年）。論文値 75.80 はこの振れ幅の中に入っており、未婚の差は「公開表だけでは決まらない仮定の選び方」の範囲内にあります。
- **死別 W を最も動かすのはコホートの打ち切り年齢**（単独で 2.58年）。死別は最も高齢で死ぬ状態なので、上限年齢の扱いが直接効きます。
- **再婚の `tail_years` はほとんど効かない**（最大でも離別 V の 0.17年）。README が仮定として挙げているものの中では、実際の影響は最小でした。

これは信頼区間ではありません。標本誤差ではなく、「分析者が選びえた仮定の範囲」の上での答えの広がりです。

## 「型」が防ぐもの

型は2つの層で検査されます。**意味の層**（`kind`、遷移の始点終点、母集団、推計品質、オントロジー）と、**次元の層**（単位の代数）です。

- `S→M` の初婚数を `M` の exposure で割る、といった分母状態の取り違え。
- 死亡数の `person` と exposure の `person-year` の意味混同。単位は基本次元 `person`・`year` 上の指数ベクトルなので、`person / (person-year) = 1/year` が**宣言ではなく計算で**出ます。人年でなく人頭数を分母に渡すと結果が無次元になり、ハザードとして弾かれます。
- 「前婚解消時年齢」を「再婚時年齢」と無注記で同一視すること。
- 2024年の配偶状態人口推計を観測値として扱うこと。推計値の型はさらに、依存している仮定の集合を持ちます。
- オントロジーに存在しない遷移をモデルへ混入すること。許されていない遷移のハザードは、生成子行列に入る前に拒否されます。

各変換は「型付け規則（signature）」と「行の計算」に分かれており、`check` と `run` は同じ signature を呼びます。したがって検査した型と実際に生成される型が食い違うことは起こりません。詳細は `docs/type_system.md`。

## 今回の推計に残る仮定

1. **年齢階級:** 公開表の整合性を優先し `15–19, ... , 75–79, 80+` の5歳階級に統一。
2. **2024年配偶状態割合:** 2015・2020年の国勢調査（不詳補完値を優先）から各年齢階級の割合を線形外挿し、負値を0にして再正規化。
3. **再婚:** 中巻7の「前婚解消時年齢 + 解消からの年数」から再婚時年齢を導出。11年以上前は12年として代表させるため `Estimated` 型。
4. **5年遷移:** 年齢階級内で年率が一定と仮定し `P=expm(5G)` で5年間の遷移確率を生成。
5. **80+ open interval:** 80歳以上の hazard を120歳まで一定としてsynthetic cohortを閉じる。

論文の完全再現ではありません。論文は各歳の遷移率・死亡率の平滑化、ロジスティック/ワイブル当てはめ等を行い、さらに統計法33条に基づく死亡票・婚姻票・離婚票の独自集計を含みます。そのため、公開集計表だけの実装とは数値が一致しないことがあります。

## ファイル構成

```text
mslt/
  units.py        dimensional algebra (person, year)
  assumptions.py  named assumptions + their sweep ranges
  types.py        semantic/refinement types + assumption dependency
  sensitivity.py  assumption sweep driver
  ontology.py     state-transition ontology + induced state space
  adapters.py     e-Stat / JMD semantic lift (+ type-level signatures)
  transforms.py   typing rules + typed transformations + Markov life table
  dsl.py          small DSL parser
  engine.py       static type checker + execution engine
  cli.py          check / explain / run / sensitivity
ontology/
  marital.yaml
  marital_absorbing_dissolution.yaml   再婚なしの変種
examples/
  male_2024.mslt
  male_2020_validate.mslt
data/
  jmd_exposure_5x1_2020_2024.txt
outputs/
  2020/, 2024/
docs/
  type_system.md
```
