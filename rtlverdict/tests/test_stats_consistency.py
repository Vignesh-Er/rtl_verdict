"""Phase 0 (the "freeze the numbers" pivot, FINDINGS.md): every number in
every downstream artifact must come from results/corpus_stats.json, never
be hand-typed. This file is the enforcement, not just the intent:
  - corpus_stats.json's own internal sums are re-checked independently here
    (not just trusting build_stats.py's own assertions - defense in depth)
  - every *.md under results/ and docs/ is scanned for a bare integer >= 10
    that does not appear anywhere in corpus_stats.json and is not on the
    allowlist (results/stats_allowlist.txt) - a number that fails this
    check is either a typo, a stale pre-freeze number, or a legitimate
    exception (a year, a tool version, a k-value) that belongs on the
    allowlist, explicitly, not silently.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STATS_PATH = REPO_ROOT / "results" / "corpus_stats.json"
ALLOWLIST_PATH = REPO_ROOT / "results" / "stats_allowlist.txt"


def _load_stats() -> dict:
    if not STATS_PATH.exists():
        pytest.skip(f"{STATS_PATH} not built yet - run scripts/build_stats.py first")
    return json.loads(STATS_PATH.read_text())


class TestPerDesignSums:
    def test_generated_equals_distinct_equals_recorded(self):
        stats = _load_stats()
        for d in stats["designs"]:
            assert d["generated"] == d["distinct"] == d["recorded"], (
                f"{d['name']}: generated={d['generated']} distinct={d['distinct']} "
                f"recorded={d['recorded']} - should all be equal (0 duplicates, 0 silently dropped)"
            )

    def test_verdicts_sum_to_recorded_per_design(self):
        stats = _load_stats()
        for d in stats["designs"]:
            assert sum(d["verdicts"].values()) == d["recorded"], (
                f"{d['name']}: verdict counts {d['verdicts']} sum to "
                f"{sum(d['verdicts'].values())}, expected {d['recorded']}"
            )

    def test_corpus_totals_equal_sum_of_per_design(self):
        stats = _load_stats()
        designs = stats["designs"]
        totals = stats["corpus_totals"]
        assert totals["generated"] == sum(d["generated"] for d in designs)
        assert totals["distinct"] == sum(d["distinct"] for d in designs)
        assert totals["recorded"] == sum(d["recorded"] for d in designs)
        for verdict in ("KEEP", "QUARANTINE", "SILENT", "ERROR"):
            expected = sum(d["verdicts"].get(verdict, 0) for d in designs)
            assert totals["verdicts"][verdict] == expected, (
                f"corpus_totals.verdicts[{verdict}]={totals['verdicts'][verdict]} "
                f"!= sum over designs ({expected})"
            )


class TestOperatorSums:
    def test_operator_candidates_sum_to_corpus_total(self):
        stats = _load_stats()
        total = sum(op["candidates"] for op in stats["operators"])
        assert total == stats["corpus_totals"]["recorded"], (
            f"sum of per-operator candidates ({total}) != corpus total recorded "
            f"({stats['corpus_totals']['recorded']})"
        )

    def test_operator_verdicts_sum_to_candidates(self):
        stats = _load_stats()
        for op in stats["operators"]:
            assert sum(op["verdicts"].values()) == op["candidates"], f"operator {op['name']}: verdict mismatch"


class TestSilentBugRate:
    def test_numerator_denominator_consistent_with_per_design(self):
        stats = _load_stats()
        sbr = stats["silent_bug_rate"]
        assert sbr["numerator"] == sum(d["silent"] for d in sbr["per_design"])
        assert sbr["denominator"] == sum(d["n"] for d in sbr["per_design"])

    def test_definition_field_present_and_nonempty(self):
        stats = _load_stats()
        assert stats["silent_bug_rate"]["definition"].strip()


class TestEveryFieldHasProvenance:
    def test_provenance_field_sources_covers_top_level_keys(self):
        stats = _load_stats()
        sources = stats["provenance"]["field_sources"]
        # every top-level data key (excluding provenance/toolchain_versions,
        # which are self-describing) must have a stated source
        for key in ("designs", "operators", "silent_bug_rate", "equivalent_mutant_promotion", "coverage"):
            matching = [k for k in sources if key in k or k.startswith(key)]
            assert matching, f"no provenance.field_sources entry mentions {key!r}"


# ---------------------------------------------------------------------------
# Bare-integer sweep: every number >=10 appearing in results/*.md and
# docs/*.md must be traceable to corpus_stats.json or explicitly allowlisted.
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_URL_RE = re.compile(r"https?://\S+")
_TABLE_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")
# A bare integer: not immediately preceded/followed by a digit, dot, or
# hyphen (excludes version strings "0.68", dates "2026-08-09", "v5.051",
# task ids "_014", percentages' decimal part "37.6" already caught via the
# integer part separately - intentional, the integer part of a rate still
# needs to trace back to corpus_stats.json).
_BARE_INT_RE = re.compile(r"(?<![\d.\-_])\d{2,}(?![\d.])")


def _strip_noise(text: str) -> str:
    text = _CODE_FENCE_RE.sub("", text)
    text = _INLINE_CODE_RE.sub("", text)
    text = _URL_RE.sub("", text)
    lines = [line for line in text.splitlines() if not _TABLE_SEP_RE.match(line)]
    return "\n".join(lines)


def _extract_prose_integers(text: str) -> set[int]:
    cleaned = _strip_noise(text)
    return {int(m) for m in _BARE_INT_RE.findall(cleaned)}


def _flatten_numbers(obj) -> set[int]:
    found: set[int] = set()
    if isinstance(obj, bool):
        return found
    if isinstance(obj, int):
        found.add(obj)
    elif isinstance(obj, float):
        found.add(int(obj))
        # a rate like 37.6% - also allow the rounded/truncated forms a
        # human might quote in prose (37 or 38)
        found.add(int(obj) + 1)
    elif isinstance(obj, dict):
        for v in obj.values():
            found |= _flatten_numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            found |= _flatten_numbers(v)
    return found


def _load_allowlist() -> set[int]:
    if not ALLOWLIST_PATH.exists():
        return set()
    allowed = set()
    for line in ALLOWLIST_PATH.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line.isdigit():
            allowed.add(int(line))
    return allowed


class TestNoUntracedNumbers:
    @pytest.mark.parametrize(
        "md_path",
        sorted((REPO_ROOT / "results").glob("*.md")) + sorted((REPO_ROOT / "docs").glob("*.md")),
        ids=lambda p: str(p.relative_to(REPO_ROOT)),
    )
    def test_every_bare_integer_traces_to_stats_or_allowlist(self, md_path: Path):
        stats = _load_stats()
        known = _flatten_numbers(stats) | _load_allowlist()
        found = _extract_prose_integers(md_path.read_text())
        untraced = sorted(found - known)
        assert not untraced, (
            f"{md_path.relative_to(REPO_ROOT)} has bare integer(s) not in corpus_stats.json "
            f"or results/stats_allowlist.txt: {untraced} - either the doc is stale "
            f"(regenerate from corpus_stats.json) or these are legitimate exceptions "
            f"(years, tool versions, k-values) that need an explicit allowlist entry"
        )
