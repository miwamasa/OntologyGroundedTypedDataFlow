"""The named assumptions this pipeline's estimates rest on.

`Quality.ESTIMATED` records that a number is not an observation. That is a
one-bit answer to a question worth more: *estimated on what, and how much does
it move if that changes?*

Each assumption below is a knob with a name, the operation that introduces it,
the parameter that carries it, and the range it is worth sweeping. The name is
what appears in a type's `depends_on` set, so the type system decides which
knobs can reach a given output -- a sweep never has to guess, and never varies
something the output provably cannot respond to.

The swept range is a stated range of modelling choices, not a probability
distribution. What comes out is the span of an indicator over choices a careful
analyst might have made, not a confidence interval.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

SHARE_EXTRAPOLATION = "share_extrapolation"
REMARRIAGE_TAIL = "remarriage_tail_years"
COHORT_CLOSURE = "cohort_closure"


@dataclass(frozen=True)
class Assumption:
    name: str
    op: str
    parameter: str
    description: str
    baseline: Any
    values: tuple

    def label(self, value: Any) -> str:
        mark = " (baseline)" if value == self.baseline else ""
        return f"{self.parameter}={value:g}{mark}" if isinstance(value, (int, float)) \
            else f"{self.parameter}={value}{mark}"


ASSUMPTIONS: dict[str, Assumption] = {
    SHARE_EXTRAPOLATION: Assumption(
        name=SHARE_EXTRAPOLATION,
        op="extrapolate_share",
        parameter="strength",
        description=(
            "2015->2020 の配偶状態割合の傾きを 2024 年へどれだけ延長するか。"
            "0 なら 2020 年の割合を据え置き、1 が線形外挿、1.5 は傾きの加速。"
        ),
        baseline=1.0,
        values=(0.0, 0.5, 1.0, 1.5),
    ),
    REMARRIAGE_TAIL: Assumption(
        name=REMARRIAGE_TAIL,
        op="estat_remarriage7",
        parameter="tail_years",
        description=(
            "中巻7の「前婚解消から11年以上」を代表させる経過年数。"
            "再婚時年齢の導出に直接効く。"
        ),
        baseline=12.0,
        values=(11.0, 12.0, 15.0),
    ),
    COHORT_CLOSURE: Assumption(
        name=COHORT_CLOSURE,
        op="multistate_life_table",
        parameter="max_age",
        description=(
            "80歳以上のハザードを一定として合成コホートを閉じる上限年齢。"
        ),
        baseline=120,
        values=(105, 120, 130),
    ),
}


def applicable(depends_on) -> list[Assumption]:
    """The declared knobs that can move a value with this dependency set."""
    return [ASSUMPTIONS[n] for n in sorted(depends_on) if n in ASSUMPTIONS]


def unknown(depends_on) -> list[str]:
    """Assumption names a type declares that no knob is registered for."""
    return sorted(n for n in depends_on if n not in ASSUMPTIONS)
