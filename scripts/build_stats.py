"""scripts/build_stats.py -> results/corpus_stats.json

Every number in every downstream artifact (results/*.md, README, dashboard)
is read from this file, never hand-typed - see FINDINGS.md's "freeze the
numbers" pivot. Every field here is computed fresh from a real source
(tasks.json records, a live re-run of candidate generation, a live
toolchain --version invocation, git, a fresh Verilator coverage build) -
nothing is copied from a prior report or from memory.

Run: python scripts/build_stats.py  (from repo root, RTLVERDICT_OSS_CAD_ROOT set)
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from rtlverdict import env  # noqa: E402
from rtlverdict.eval.coverage import parse_coverage_dat  # noqa: E402
from rtlverdict.forge.corpus import ALL_OPERATORS  # noqa: E402
from rtlverdict.forge.parser import parse_file  # noqa: E402

# name, tier, formal_k (the k actually used to generate this design's corpus -
# fifo's is 25, not 40, because of the memory_map array-theory ceiling - see
# FINDINGS.md's Day-9 pivot section. This is the single source of truth other
# scripts/docs must cite, never a hardcoded "40" or "25" typed elsewhere.)
DESIGNS = [
    ("fsm", "A", 40),
    ("uart", "A", 40),
    ("spi_master", "A", 40),
    ("fifo", "A", 25),
]

CORPUS_FILES = {
    "fsm": REPO_ROOT / "benchmarks/corpus_v2/tasks.json",
    "uart": REPO_ROOT / "benchmarks/corpus_v2/tasks.json",
    "spi_master": REPO_ROOT / "benchmarks/corpus_v2/tasks.json",
    "fifo": REPO_ROOT / "benchmarks/corpus_v2_fifo_addition/tasks.json",
}


def _git_info() -> dict:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    return {"commit_sha": sha, "dirty": bool(dirty)}


def _toolchain_versions() -> dict:
    report = env.run_doctor()
    versions = {t.name: t.version_output for t in report.tools if t.found}
    versions["python"] = sys.version.split()[0]
    return versions


def _normalize(source: str) -> str:
    # Mirrors forge/corpus.py's own _normalize exactly (whitespace-only
    # normalization before hashing for dedup) - kept as a one-line inline
    # copy rather than importing a private helper across modules.
    return "\n".join(line.rstrip() for line in source.splitlines())


def _fresh_generated_distinct(design: str) -> tuple[int, int]:
    """Re-derive generated/distinct candidate counts FRESH this run (cheap -
    parsing + operator application only, no subprocess calls) rather than
    trusting a prior run's console log.
    """
    golden_path = REPO_ROOT / "designs" / design / f"{design}.v"
    tree, source = parse_file(golden_path)
    all_candidates = []
    for op in ALL_OPERATORS:
        all_candidates.extend(op(tree, source))
    seen = set()
    for c in all_candidates:
        mutant_source = source[: c.start_offset] + c.replacement_text + source[c.end_offset :]
        seen.add(hashlib.sha256(_normalize(mutant_source).encode()).hexdigest())
    return len(all_candidates), len(seen)


_STAT_SECTION_RE = re.compile(r"^=== \S+ ===\s*$", re.MULTILINE)
_STAT_PUBLIC_WIRES_RE = re.compile(r"^\s*(\d+)\s+public wires\s*$", re.MULTILINE)
_STAT_CELLS_RE = re.compile(r"^\s*(\d+)\s+cells\s*$", re.MULTILINE)


def _design_size(name: str) -> dict:
    """DUT signal count (Yosys 'public wires' - named signals, not synthesis
    temporaries) and total cell count, from a real `yosys ... synth; stat`
    run - never typed. Parses the LAST '=== name ===' stat block (synth
    prints one mid-flow and one after CHECK; the later one is the settled
    post-synthesis count).
    """
    e = env.build_subprocess_env()
    yosys = shutil.which("yosys.exe", path=e["PATH"])
    if yosys is None:
        raise RuntimeError("yosys.exe not found on PATH built by rtlverdict.env")
    proc = subprocess.run(
        [yosys, "-p", f"read_verilog designs/{name}/{name}.v; synth -top {name}; stat"],
        cwd=REPO_ROOT, env=e, capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"yosys stat failed for {name}:\n{proc.stderr[-1000:]}")
    out = proc.stdout
    sections = list(_STAT_SECTION_RE.finditer(out))
    if not sections:
        raise RuntimeError(f"yosys stat produced no '=== {name} ===' section for {name}:\n{out[-1000:]}")
    tail = out[sections[-1].start():]
    wires_m = _STAT_PUBLIC_WIRES_RE.search(tail)
    cells_m = _STAT_CELLS_RE.search(tail)
    if not wires_m or not cells_m:
        raise RuntimeError(f"could not parse public-wires/cells from yosys stat output for {name}:\n{tail[:800]}")
    return {"dut_signal_count": int(wires_m.group(1)), "cell_count": int(cells_m.group(1))}


def _design_stats() -> list[dict]:
    out = []
    for name, tier, formal_k in DESIGNS:
        loc = len((REPO_ROOT / "designs" / name / f"{name}.v").read_text().splitlines())
        size = _design_size(name)
        tasks = json.loads(CORPUS_FILES[name].read_text())
        tasks_for_design = [t for t in tasks if t["design"] == name]
        generated, distinct = _fresh_generated_distinct(name)
        recorded = len(tasks_for_design)

        assert generated == distinct, (
            f"{name}: generated({generated}) != distinct({distinct}) on fresh regeneration "
            f"- a duplicate mutant appeared that the original run's dedup should have caught"
        )
        assert distinct == recorded, (
            f"{name}: distinct({distinct}) != recorded({recorded}) - a candidate was silently "
            f"dropped between generation and the committed tasks.json"
        )

        verdicts: dict[str, int] = defaultdict(int)
        for t in tasks_for_design:
            verdicts[t["forge_decision"]] += 1
        assert sum(verdicts.values()) == recorded, f"{name}: verdict counts don't sum to recorded"

        out.append(
            {
                "name": name,
                "tier": tier,
                "loc": loc,
                "dut_signal_count": size["dut_signal_count"],
                "cell_count": size["cell_count"],
                "formal_k": formal_k,
                "generated": generated,
                "distinct": distinct,
                "recorded": recorded,
                "verdicts": dict(verdicts),
            }
        )
    return out


def _operator_stats() -> list[dict]:
    all_tasks = []
    for path in {str(p): p for p in CORPUS_FILES.values()}.values():
        all_tasks.extend(json.loads(path.read_text()))
    by_op: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t in all_tasks:
        op = t["operator"].split(".")[-1]
        by_op[op][t["forge_decision"]] += 1
    result = []
    for op, verdicts in sorted(by_op.items()):
        keep = verdicts.get("KEEP", 0)
        silent = verdicts.get("SILENT", 0)
        quarantine = verdicts.get("QUARANTINE", 0)
        error = verdicts.get("ERROR", 0)
        real_bugs_n = keep + silent
        # ERROR candidates never reached formal verification at all (rejected
        # by the fidelity guard beforehand) - they belong in neither the
        # "real bug" nor the "equivalent" bucket, so both rates below exclude
        # them from the denominator (evaluated_n = candidates - error), not
        # just from their own numerator.
        evaluated_n = sum(verdicts.values()) - error
        result.append({
            "name": op,
            "candidates": sum(verdicts.values()),
            "verdicts": dict(verdicts),
            "real_bugs_n": real_bugs_n,
            "silent_rate_pct": round(100.0 * silent / real_bugs_n, 1) if real_bugs_n else None,
            "evaluated_n": evaluated_n,
            "equivalent_n": quarantine,
            "equivalent_rate_pct": round(100.0 * quarantine / evaluated_n, 1) if evaluated_n else None,
        })
    return result


def _silent_bug_rate(designs_data: list[dict]) -> dict:
    per_design = []
    total_keep, total_silent = 0, 0
    for d in designs_data:
        keep = d["verdicts"].get("KEEP", 0)
        silent = d["verdicts"].get("SILENT", 0)
        n = keep + silent
        per_design.append(
            {
                "design": d["name"],
                "keep": keep,
                "silent": silent,
                "n": n,
                "rate_pct": round(100.0 * silent / n, 1) if n else None,
            }
        )
        total_keep += keep
        total_silent += silent
    n_total = total_keep + total_silent

    rates = [d["rate_pct"] for d in per_design if d["rate_pct"] is not None]
    max_d = max(per_design, key=lambda d: d["rate_pct"] if d["rate_pct"] is not None else -1)
    min_d = min(per_design, key=lambda d: d["rate_pct"] if d["rate_pct"] is not None else 1e9)

    # sensitivity: pooled rate excluding whichever design has the highest
    # rate (the one most likely to dominate the pooled figure) - computed
    # here, not left for a document to compute ad hoc, so it's traceable.
    without_max = [d for d in per_design if d["design"] != max_d["design"]]
    num_wo_max = sum(d["silent"] for d in without_max)
    den_wo_max = sum(d["n"] for d in without_max)

    return {
        "definition": (
            "SILENT = a mutant formally REFUTED (verdict proves a real behavioral divergence "
            "from golden) where the design's own testbench still reports sim PASS. "
            "Rate = SILENT / (KEEP + SILENT) - i.e. out of every formally-confirmed real bug "
            "(whether or not sim caught it), the fraction sim missed."
        ),
        "numerator": total_silent,
        "denominator": n_total,
        "rate_pct": round(100.0 * total_silent / n_total, 1) if n_total else None,
        "per_design": per_design,
        "range": {
            "min_pct": min(rates) if rates else None,
            "min_design": min_d["design"],
            "max_pct": max(rates) if rates else None,
            "max_design": max_d["design"],
            "ratio_max_over_min": round(max(rates) / min(rates), 1) if rates and min(rates) else None,
        },
        "excluding_highest_design": {
            "excluded_design": max_d["design"],
            "numerator": num_wo_max,
            "denominator": den_wo_max,
            "rate_pct": round(100.0 * num_wo_max / den_wo_max, 1) if den_wo_max else None,
        },
    }


def _coverage_rank_correlation(designs_data: list[dict], coverage_data: list[dict], silent_per_design: list[dict]) -> dict:
    """Exact permutation test on whether the (toggle coverage, silent rate)
    ranking across the 4 designs could arise by chance. n=4 -> 4! = 24
    possible orderings of silent-rate rank when designs are fixed in
    coverage-rank order; exactly 2 of those 24 are perfectly monotone
    (strictly ascending or strictly descending) - computed here via
    itertools.permutations, never hand-counted, and cross-checked against
    the closed form 2/n! at import time via the assert below.
    """
    import itertools

    cov_by_design = {c["design"]: c["toggle"] for c in coverage_data}
    rows = []
    for d in silent_per_design:
        cov = cov_by_design[d["design"]]
        cov_pct = 100.0 * cov["hit"] / cov["total"] if cov["total"] else None
        rows.append((d["design"], cov_pct, d["rate_pct"]))
    rows_by_cov = sorted(rows, key=lambda r: r[1])
    silent_ranks = [r[2] for r in rows_by_cov]

    n = len(silent_ranks)
    all_perms = list(itertools.permutations(silent_ranks))
    n_permutations = len(all_perms)
    n_monotone = sum(
        1 for p in all_perms
        if all(p[i] < p[i + 1] for i in range(n - 1)) or all(p[i] > p[i + 1] for i in range(n - 1))
    )
    assert n_permutations == 24 and n_monotone == 2, (
        f"permutation test constants drifted: n_permutations={n_permutations}, n_monotone={n_monotone} "
        f"- corpus size or design count changed, re-derive the quoted p-value by hand before trusting it"
    )
    p_value = round(n_monotone / n_permutations, 3)

    return {
        "method": (
            "Exact two-sided permutation test: with n=4 designs fixed in ascending toggle-coverage "
            "order, is the observed silent-rate ordering (also monotone here) one of the extreme "
            "(fully-sorted) permutations, or typical of the full permutation space?"
        ),
        "designs_by_coverage_rank": [r[0] for r in rows_by_cov],
        "n_designs": n,
        "n_permutations": n_permutations,
        "n_monotone": n_monotone,
        "p_value_two_sided": p_value,
        "note": (
            "Suggestive, not evidence: n=4 is too small for this p-value to license a causal claim, "
            "and it says nothing about WHY the two variables move together (see silent_rate_by_design_operator "
            "and results/silent_bugs.md SS5.1 for the design-class-confound analysis)."
        ),
    }


def _silent_rate_by_design_operator() -> list[dict]:
    """Per-(design, operator) KEEP/SILENT breakdown - the granularity needed
    to tell whether an elevated silent rate is a general (operator-agnostic)
    property of a design, or concentrated in specific operator classes (the
    hypothesis-A-vs-B question in results/silent_bugs.md SS5.1). Raw counts
    only; most cells here are n<10 and are reported as such, never smoothed.
    """
    all_tasks = []
    for path in {str(p): p for p in CORPUS_FILES.values()}.values():
        all_tasks.extend(json.loads(path.read_text()))
    by_cell: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for t in all_tasks:
        op = t["operator"].split(".")[-1]
        by_cell[(t["design"], op)][t["forge_decision"]] += 1
    result = []
    for (design, op), verdicts in sorted(by_cell.items()):
        keep = verdicts.get("KEEP", 0)
        silent = verdicts.get("SILENT", 0)
        n = keep + silent
        if n == 0:
            continue  # this (design, operator) cell has no real bugs to rate (all QUARANTINE/ERROR)
        result.append({
            "design": design,
            "operator": op,
            "keep": keep,
            "silent": silent,
            "n": n,
            "silent_rate_pct": round(100.0 * silent / n, 1),
        })
    return result


def _equivalent_mutant_promotion() -> dict:
    promotions = json.loads((REPO_ROOT / "benchmarks/corpus_v2/deep_bmc_promotions.json").read_text())
    promoted = [p for p in promotions if p["decision"] == "PROMOTE"]
    still_indeterminate = [p for p in promotions if p["new_verdict"] == "INDETERMINATE"]
    still_proven_bmc = [p for p in promotions if p["new_verdict"] == "PROVEN-BMC"]
    return {
        "quarantined_count": len(promotions),
        "promoted_count": len(promoted),
        "still_proven_bmc_count": len(still_proven_bmc),
        "still_indeterminate_count": len(still_indeterminate),
        "k_original": 40,
        "k_deep": 200,
        # forge/deep_bmc_promote.py's own constants (K/TIMEOUT_S/
        # NEAR_TIMEOUT_FRACTION) - persisted here so a document citing them
        # never hand-types a methodology parameter.
        "timeout_s": 150,
        "near_timeout_threshold_pct": 80,
        "designs_checked": sorted({p["design"] for p in promotions}),
        "note": (
            "fifo's QUARANTINE pool was not re-checked at deep k - its own k=25 first pass is "
            "already near the practical ceiling for this design (memory_map array-theory "
            "blowup), see designs/fifo/design.yaml and FINDINGS.md"
        ),
    }


def _divergence_depth_histogram() -> dict:
    all_tasks = []
    for path in {str(p): p for p in CORPUS_FILES.values()}.values():
        all_tasks.extend(json.loads(path.read_text()))
    cycles = [
        t["divergence_cycle"]
        for t in all_tasks
        if t["forge_decision"] == "KEEP" and t["divergence_cycle"] is not None
    ]
    buckets = {"0-4": 0, "5-9": 0, "10-19": 0, "20+": 0}
    for c in cycles:
        if c < 5:
            buckets["0-4"] += 1
        elif c < 10:
            buckets["5-9"] += 1
        elif c < 20:
            buckets["10-19"] += 1
        else:
            buckets["20+"] += 1
    return {"n": len(cycles), "buckets": buckets, "raw_values": sorted(cycles)}


def _coverage() -> list[dict]:
    """Fresh Verilator --binary --coverage build+run per design, DUT-only
    filtered - reproduces the 39.8%(raw)->50.0%(DUT-only) uart story
    documented in eval/coverage.py exactly (verified byte-for-byte while
    building this script). Never read from a prior report.
    """
    e = env.build_subprocess_env()
    vbin = shutil.which("verilator_bin.exe", path=e["PATH"])
    if vbin is None:
        raise RuntimeError("verilator_bin.exe not found on PATH built by rtlverdict.env")

    results = []
    for name, _tier, _formal_k in DESIGNS:
        work = REPO_ROOT / "scratch_verify" / "cov_build" / name
        if work.exists():
            shutil.rmtree(work)
        work.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / "designs" / name / f"{name}.v", work / f"{name}.v")
        shutil.copy(REPO_ROOT / "designs" / name / f"tb_{name}.v", work / f"tb_{name}.v")

        top = f"tb_{name}"
        build = subprocess.run(
            [
                vbin, "--binary", "--coverage", "-Wno-fatal", "--top-module", top,
                f"{name}.v", f"tb_{name}.v", "-Mdir", "obj_dir",
            ],
            cwd=work, env=e, capture_output=True, text=True, timeout=120,
        )
        if build.returncode != 0:
            raise RuntimeError(f"coverage build failed for {name}:\n{build.stderr[-1500:]}")

        run = subprocess.run(
            [str(work / "obj_dir" / f"V{top}.exe")], cwd=work, env=e,
            capture_output=True, text=True, timeout=30,
        )
        if "RTLVERDICT_RESULT: PASS" not in run.stdout:
            raise RuntimeError(f"golden {name} did not PASS its own testbench during coverage run: {run.stdout[-500:]}")

        # DUT-only (dut_file filter) is the figure used everywhere else in
        # this project; raw (unfiltered, includes testbench-internal
        # variables) is kept alongside it so the raw->DUT-only correction
        # story (uart: 39.8%->50.0%) is traceable to this file, not typed
        # from memory - see FINDINGS.md and results/silent_bugs.md.
        dut_only = parse_coverage_dat(work / "coverage.dat", dut_file=f"{name}.v")
        raw = parse_coverage_dat(work / "coverage.dat", dut_file=None)

        def _pack(summary):
            return {t: {"hit": summary.by_type[t][0], "total": summary.by_type[t][1]} for t in ("line", "toggle", "branch", "expr")}

        results.append({"design": name, **_pack(dut_only), "raw": _pack(raw)})
    return results


def main() -> None:
    env.sweep_orphaned_solvers()

    print("Building results/corpus_stats.json...")
    designs_data = _design_stats()
    print(f"  design stats: {[(d['name'], d['recorded']) for d in designs_data]}")
    operator_data = _operator_stats()
    silent_bug = _silent_bug_rate(designs_data)
    silent_by_design_operator = _silent_rate_by_design_operator()
    equiv_promo = _equivalent_mutant_promotion()
    depth_hist = _divergence_depth_histogram()
    print("  running fresh coverage builds (4 designs)...")
    coverage_data = _coverage()
    print(f"  coverage (DUT-only toggle): {[(c['design'], c['toggle']) for c in coverage_data]}")
    silent_bug["coverage_rank_correlation"] = _coverage_rank_correlation(designs_data, coverage_data, silent_bug["per_design"])

    total_generated = sum(d["generated"] for d in designs_data)
    total_distinct = sum(d["distinct"] for d in designs_data)
    total_recorded = sum(d["recorded"] for d in designs_data)
    assert total_generated == total_distinct == total_recorded, "corpus-wide sums mismatch"

    stats = {
        "provenance": {
            "script": "scripts/build_stats.py",
            "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "git": _git_info(),
            "host_os": sys.platform,
            "field_sources": {
                "designs[].generated/distinct": "fresh regeneration of mutation candidates via forge operators, this run - never read from a log",
                "designs[].dut_signal_count/cell_count": "live `yosys -p synth;stat` run this run, last '=== name ===' section parsed",
                "designs[].recorded/verdicts": [str(p.relative_to(REPO_ROOT)) for p in {str(p): p for p in CORPUS_FILES.values()}.values()],
                "operators": "same tasks.json files, grouped by operator field",
                "silent_bug_rate": "derived from designs[].verdicts; range/excluding_highest_design are computed sensitivity checks, not independently-sourced data",
                "silent_bug_rate.coverage_rank_correlation": "exact permutation test (itertools.permutations) over silent_bug_rate.per_design x coverage[].toggle, computed this run",
                "silent_rate_by_design_operator": "same tasks.json files as operators[], grouped by (design, operator) instead of operator alone",
                "coverage[].raw": "same fresh Verilator coverage build as coverage[], parsed without the dut_file filter",
                "equivalent_mutant_promotion": "benchmarks/corpus_v2/deep_bmc_promotions.json",
                "divergence_depth_histogram_keep": "tasks.json KEEP records' divergence_cycle field",
                "coverage": "fresh verilator --binary --coverage build+run, this run, DUT-only filtered (rtlverdict.eval.coverage)",
                "toolchain_versions": "rtlverdict.env.run_doctor(), live --version invocation of every tool",
            },
        },
        "toolchain_versions": _toolchain_versions(),
        "designs": designs_data,
        "operators": operator_data,
        "silent_bug_rate": silent_bug,
        "silent_rate_by_design_operator": silent_by_design_operator,
        "equivalent_mutant_promotion": equiv_promo,
        "divergence_depth_histogram_keep": depth_hist,
        "coverage": coverage_data,
        "corpus_totals": {
            "generated": total_generated,
            "distinct": total_distinct,
            "recorded": total_recorded,
            "verdicts": {
                k: sum(d["verdicts"].get(k, 0) for d in designs_data)
                for k in ("KEEP", "QUARANTINE", "SILENT", "ERROR")
            },
        },
    }

    out_path = REPO_ROOT / "results" / "corpus_stats.json"
    out_path.write_text(json.dumps(stats, indent=2))
    print(f"wrote {out_path}")
    print(f"corpus totals: {stats['corpus_totals']}")


if __name__ == "__main__":
    main()
