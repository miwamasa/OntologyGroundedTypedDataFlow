"""Sweep the assumptions an output actually rests on.

The type system has already worked out which named assumptions reach a given
node. This module does the corresponding arithmetic: re-run the program with
those knobs moved, and report how far the answer travels.

Two readings are produced. *One-at-a-time* moves a single assumption and holds
the rest at baseline, which attributes movement to a specific modelling choice.
The *envelope* takes every combination, giving the span of the indicator across
the whole declared range.

Neither is a confidence interval. The inputs are stated ranges of defensible
modelling choices, so the output is the span of the answer over those choices
-- sampling error and the accuracy of the published tables are not in it.
"""
from __future__ import annotations
from itertools import product

from .assumptions import Assumption, ASSUMPTIONS, applicable, unknown
from .engine import Engine


def readout(frame) -> dict[str, float]:
    """Flatten an indicator frame to label -> value."""
    out = {}
    for r in frame.rows:
        if r.get("value") is None:
            continue
        label = f"{r['indicator']}/{r['state']}" if "indicator" in r else str(r)
        out[label] = float(r["value"])
    return out


def _run(program, data_root, ontology, target, overrides, cache):
    env = Engine(program, data_root, ontology, overrides=overrides, source_cache=cache).run()
    if target not in env:
        raise KeyError(f"program has no node named {target!r}; found {sorted(env)}")
    return readout(env[target])


def _span(values: list[dict[str, float]]) -> dict[str, dict]:
    labels = [k for k in values[0]] if values else []
    out = {}
    for label in labels:
        seen = [v[label] for v in values if label in v]
        out[label] = {"min": min(seen), "max": max(seen), "span": max(seen) - min(seen)}
    return out


def sweep(program: str, data_root: str = ".", ontology: str | None = None,
          target: str = "indicators", envelope: bool = True) -> dict:
    """Vary every declared assumption the target depends on, and nothing else."""
    cache: dict = {}
    static = Engine(program, data_root, ontology).typecheck()
    if target not in static:
        raise KeyError(f"program has no node named {target!r}; found {sorted(static)}")
    depends = static[target].depends_on
    knobs = applicable(depends)
    missing = unknown(depends)

    baseline = _run(program, data_root, ontology, target, None, cache)

    one_at_a_time = {}
    for knob in knobs:
        points = []
        for value in knob.values:
            r = (baseline if value == knob.baseline
                 else _run(program, data_root, ontology, target,
                           {knob.op: {knob.parameter: value}}, cache))
            points.append({"value": value, "label": knob.label(value), "indicators": r})
        one_at_a_time[knob.name] = {
            "parameter": knob.parameter,
            "operation": knob.op,
            "description": knob.description,
            "baseline": knob.baseline,
            "points": points,
            "range": _span([p["indicators"] for p in points]),
        }

    report = {
        "program": program,
        "target": target,
        "depends_on": sorted(depends),
        "swept": [k.name for k in knobs],
        "unregistered": missing,
        # Registered knobs the type system proves cannot reach this target, so
        # the sweep does not spend runs on them.
        "not_applicable": sorted(set(ASSUMPTIONS) - set(depends)),
        "baseline": baseline,
        "one_at_a_time": one_at_a_time,
    }

    if envelope and knobs:
        combos = list(product(*[k.values for k in knobs]))
        results = []
        for combo in combos:
            ov = {k.op: {k.parameter: v} for k, v in zip(knobs, combo)}
            results.append(_run(program, data_root, ontology, target, ov, cache))
        report["envelope"] = {
            "combinations": len(combos),
            "range": _span(results),
        }
    return report


def format_report(report: dict) -> str:
    """Render a sweep as a readable table."""
    lines = [f"target: {report['target']}  ({report['program']})"]
    lines.append(f"depends on: {', '.join(report['depends_on']) or '(nothing: fully observed)'}")
    if report["not_applicable"]:
        lines.append(f"cannot be moved by: {', '.join(report['not_applicable'])}")
    if report["unregistered"]:
        lines.append(f"declared but no knob registered: {', '.join(report['unregistered'])}")

    labels = list(report["baseline"])
    width = max((len(l) for l in labels), default=0)

    lines.append("\nbaseline")
    for l in labels:
        lines.append(f"  {l.ljust(width)}  {report['baseline'][l]:10.4f}")

    for name, block in report["one_at_a_time"].items():
        values = ", ".join(f"{p['value']:g}" for p in block["points"])
        lines.append(f"\n{name}  [{block['parameter']} in {values}]")
        lines.append(f"  {block['description']}")
        for l in labels:
            r = block["range"].get(l)
            if r is None: continue
            lines.append(f"  {l.ljust(width)}  {r['min']:10.4f} .. {r['max']:9.4f}   span {r['span']:7.4f}")

    env = report.get("envelope")
    if env:
        lines.append(f"\nenvelope over {len(report['swept'])} assumptions "
                     f"({env['combinations']} combinations)")
        for l in labels:
            r = env["range"].get(l)
            if r is None: continue
            lines.append(f"  {l.ljust(width)}  {r['min']:10.4f} .. {r['max']:9.4f}   "
                         f"span {r['span']:7.4f}   baseline {report['baseline'][l]:9.4f}")
    return "\n".join(lines)
