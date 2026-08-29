# Semantic type system

この実装では、CSV の列型ではなく「統計量の意味」を型にする。

```text
DeathCount[year,sex,age,state; person]
MaritalPopulation[year,sex,age,state; person]
MaritalShare[year,sex,age,state; proportion]
Exposure[year,sex,age; person-year]
StateExposure[year,sex,age,state; person-year]
TransitionCount<S->M>[year,sex,age; person]
HazardRate<S->M>[year,sex,age; 1/year]
GeneratorMatrix[year,sex,age; 1/year]
TransitionMatrix[year,sex,age; probability]
MultiStateLifeTable[age,state; person]
LifeCourseIndicator[indicator,state; mixed]
```

型は2つの層で検査される。**意味の層**（`kind`、遷移の始点終点、母集団、推計品質）と、**次元の層**（`unit`）である。

## 静的型検査

`mslt check` はパイプラインを**型の解釈だけで評価する**。CSV は1バイトも開かない。

```bash
# データが1つも無くても、型付けの誤りは検出される
PYTHONPATH=typed_mslt python -m mslt check typed_mslt/examples/type_error_demo.mslt --data-root /nonexistent
# ERROR: partition_exposure: expected Exposure, got DeathCount[...; person]
```

各変換は2つに分かれている。

- **signature** (`sig_*` in `transforms.py`): 入力の `SemanticType` から出力の `SemanticType` を導く関数。
- **transformation**: 行を計算し、**自分の signature に型を問い合わせて**返す。

型付け規則の定義が1箇所しかないため、`check` が導く型と `run` が実際に生成する型が食い違うことは構造的に起こらない（`tests/test_typecheck.py::test_checker_and_evaluator_agree_on_every_type` がこれを検証する）。

アダプタも同様に `ty_*` という型レベルの対応物を持つ。統計表の意味型は「どの表を、どの引数で読むか」だけで決まり、ファイルの中身には依存しないので、データ無しで評価できる。

## 単位の代数

`unit` は表示用の文字列ではなく、基本次元 `person`・`year` 上の指数ベクトルである（`mslt/units.py`）。

```text
person / (person-year)  =  1/year        occurrence-exposure rate
(person-year) × proportion = person-year  state-specific exposure
(1/year) × year         =  1             expm(G·t) の引数
person / person         =  1             marital share
```

重要なのは、**`1/year` が宣言ではなく計算で出る**という点である。分母に人年ではなく人頭数を渡すと、結果は無次元になり、ハザードにならないので弾かれる。

```text
death_hazard: state-specific exposure must be measured in person-year, got person
```

`kind` の検査だけではこれは捕まらない。`Exposure` という名前を持ちながら中身が人頭数、という型は `kind` 的には正しいからである。

### 出来事の数は人の数

初婚・離婚・死別・再婚の件数は `person` を単位とする。占有—曝露率の分子は「その事象を経験した人の数」を数えているからで、これによって死亡ハザードと社会的遷移ハザードの双方が同じ `1/year` に導出される。（`event` は `person` の別名として読み込みは受け付ける。）

### 無次元量には名前を付けられる

`proportion` と `probability` はどちらも無次元で、次元としては等しい。表示上の名前は `Unit.labeled()` で付けるが、これは**無次元であることが導出できた場合にのみ**許される。名前が導出を置き換えることはない。

`mixed`（`LifeCourseIndicator`）は行ごとに単位が異なるため不透明単位として扱い、次元演算を拒否する。

## Refinement / quality

`Observed<T>` と `Estimated<T>` を区別する。今回の 2024 配偶状態割合は国勢調査の直接観測ではないため、

```text
Estimated<MaritalShare[2024]>
```

となり、その推計性は下流へ伝播する。

```text
Observed<Exposure> × Estimated<MaritalShare>
    -> Estimated<StateExposure>
    -> Estimated<HazardRate>
    -> Estimated<MultiStateLifeTable>
```

品質は2点束 `Observed ⊑ Estimated` 上の join である。

## Ontology-licensed transitions

```text
S NeverMarried
M Married
W Widowed
V Divorced
D Dead

S -> M  first marriage
M -> W  spouse death
M -> V  divorce
W -> M  remarriage after widowhood
V -> M  remarriage after divorce
S,M,W,V -> D death
```

DSL で宣言した遷移は `ontology/marital.yaml` に存在しなければ型検査段階で拒否される。

## オントロジーはモデルの形を決める

オントロジーは検査表ではなく、**モデルの構成要素**である。`transforms.py` には状態の一覧も行列の大きさも書かれていない。すべて YAML から導出される。

| 導出されるもの | 由来 |
|---|---|
| 生存状態の集合と順序 | `states` のうち `absorbing` でないもの |
| 吸収状態 `D_S, D_M, D_W, D_V` | 生存状態ごとに `absorbing` を分割 |
| 生成子行列 G(x) の大きさ | `2 × 生存状態数`（婚姻モデルでは 8×8） |
| G(x) の疎構造（どのセルに質量を置けるか） | `transitions` |
| 合成コホートの初期状態として許される状態 | 生存状態 |
| 指標の対照状態 `NON_S` | `reference_state` |

死亡を生存状態ごとの吸収状態に分割するのは、「死亡時の状態別平均年齢」を回収するためである。どの状態から吸収されたかを行列が覚えている必要がある。

`mslt check` は導出されたモデルの形を表示する:

```text
ontology marital: living [S NeverMarried, M Married, W Widowed, V Divorced];
absorbing D split by origin into 4; generator 8x8;
social transitions S->M, M->W, M->V, W->M, V->M
```

### オントロジーの差し替え

```bash
mslt check examples/male_2024.mslt --ontology ontology/marital_absorbing_dissolution.yaml
# ERROR: source remarriage_w: transition W->M is not licensed by
#        ontology 'marital_absorbing_dissolution'
```

プログラム側から宣言することもできる:

```text
set ontology = "../ontology/marital_absorbing_dissolution.yaml"
```

許可されていない遷移のハザードは、**データを1バイトも読む前に**拒否される。オントロジーが飾りではなく構造上の制約として効いていることの確認になる。

### 婚姻に固有ではない

`mslt` のコア（状態空間・ハザード・生成子・`expm`・合成コホート・指標）はオントロジーだけに依存し、婚姻という主題を知らない。婚姻固有なのは `adapters.py` だけである。3状態の健康モデル（健康 H / 要介護 C / 死亡 D）を与えれば 4×4 の生成子が構成され、同じ機械がそのまま動く（`tests/test_ontology_driven.py`）。

## Core typing rules

```text
MaritalPopulation -> MaritalShare
Exposure × MaritalShare -> StateExposure
TransitionCount<i->j> / StateExposure<i> -> HazardRate<i->j>
DeathCount<i> / StateExposure<i> -> HazardRate<i->D>
HazardRate[*] -> GeneratorMatrix
GeneratorMatrix --expm(G*n)--> TransitionMatrix
TransitionMatrix × SyntheticCohort -> MultiStateLifeTable
MultiStateLifeTable -> LifeCourseIndicator
```

## Semantic error examples

| 誤り | 検出する層 |
|---|---|
| `partition_exposure` に `DeathCount` を渡す | `kind` |
| `Exposure` と称して人頭数（`person`）を渡す | 単位 |
| 死亡数を人頭数で割って `HazardRate` と称する | 単位（無次元になる） |
| `1/year` でない生成子を `expm` にかける | 単位（`G·t` が無次元にならない） |
| `TransitionCount<S->M>` を `StateExposure<M>` で割る | `kind` + 遷移の始点 |
| 2024 推計人口を `Observed<Population>` と宣言する | quality refinement |
| オントロジーに無い遷移を混入させる | ontology |
| 期間の推移確率を経ずに合成コホートを回す | `time_semantics` |
