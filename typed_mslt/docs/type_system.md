# Semantic type system

この実装では、CSV の列型ではなく「統計量の意味」を型にする。

```text
DeathCount[year,sex,age,state; person]
MaritalPopulation[year,sex,age,state; person]
MaritalShare[year,sex,age,state; proportion]
Exposure[year,sex,age; person-year]
StateExposure[year,sex,age,state; person-year]
TransitionCount<S->M>[year,sex,age; event]
HazardRate<S->M>[year,sex,age; 1/year]
GeneratorMatrix[year,sex,age; 1/year]
TransitionMatrix[year,sex,age; probability]
MultiStateLifeTable[age,state; persons]
LifeCourseIndicator[indicator,state]
```

## Refinement / quality

`Observed<T>` と `Estimated<T>` を区別する。今回の 2024 配偶状態割合は国勢調査の直接観測ではないため、

```text
Estimated<MaritalShare[2024]>
```

となり、その推計性は下流へ伝播する。

```text
Observed<Exposure> × Estimated<MaritalShare>
    -> Estimated<StateExposure]
    -> Estimated<HazardRate]
    -> Estimated<MultiStateLifeTable]
```

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

- `Count<Death> / Count<Person>` を `HazardRate` と宣言する: person-year でないので意味型不一致。
- `TransitionCount<S->M> / StateExposure<M>`: source state が一致しない。
- `AgeAtPreviousDissolution` をそのまま `AgeAtRemarriage` とする: event-time semantics 不一致。
- 2024 推計人口を `Observed<Population>` と宣言する: quality refinement 不一致。
