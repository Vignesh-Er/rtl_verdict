import pyslang
import pytest

from rtlverdict.forge.mutate import apply_candidate, check_fidelity
from rtlverdict.forge.operators import logic, timing
from rtlverdict.forge.parser import parse_file

FSM_PATH = "designs/fsm/fsm.v"
UART_PATH = "designs/uart/uart.v"
SPI_PATH = "designs/spi_master/spi_master.v"

ALL_OPERATORS = [
    logic.operator_swap,
    logic.constant_perturbation,
    timing.blocking_nonblocking_swap,
    timing.edge_swap,
]


def _fidelity_all(path):
    tree, source = parse_file(path)
    results = []
    for op in ALL_OPERATORS:
        for cand in op(tree, source):
            mutant = apply_candidate(source, cand)
            results.append((cand, check_fidelity(source, mutant, "mutant.v", cand.line)))
    return results


class TestByteOffsetSplice:
    def test_splice_touches_only_the_candidate_span(self):
        tree, source = parse_file(FSM_PATH)
        cands = logic.operator_swap(tree, source)
        assert cands, "expected at least one operator_swap candidate in fsm.v"
        c = cands[0]
        mutant = apply_candidate(source, c)
        assert mutant[: c.start_offset] == source[: c.start_offset]
        suffix_len = len(source) - c.end_offset
        assert mutant[-suffix_len:] == source[-suffix_len:]

    def test_mutant_reparses_with_zero_diagnostics(self):
        tree, source = parse_file(FSM_PATH)
        cands = logic.operator_swap(tree, source)
        c = cands[0]
        mutant = apply_candidate(source, c)
        mutant_tree = pyslang.syntax.SyntaxTree.fromText(mutant, "mutant.v")
        assert list(mutant_tree.diagnostics) == []


class TestDiffFidelityGate:
    @pytest.mark.parametrize("path", [FSM_PATH, UART_PATH, SPI_PATH])
    def test_every_candidate_passes_fidelity(self, path):
        results = _fidelity_all(path)
        failures = [(c.operator, c.line, r.reason) for c, r in results if not r.ok]
        assert not failures, f"fidelity failures in {path}: {failures}"

    def test_total_candidates_meets_d2_gate(self):
        total = sum(len(_fidelity_all(p)) for p in [FSM_PATH, UART_PATH, SPI_PATH])
        assert total >= 50


class TestConstantPerturbationWidthSafety:
    def test_one_bit_literal_wraps_instead_of_overflowing(self):
        tree, source = parse_file(FSM_PATH)
        cands = logic.constant_perturbation(tree, source)
        one_bit = [c for c in cands if c.original_text.startswith("1'b")]
        assert one_bit, "expected at least one 1-bit literal in fsm.v"
        for c in one_bit:
            mutant = apply_candidate(source, c)
            mutant_tree = pyslang.syntax.SyntaxTree.fromText(mutant, "mutant.v")
            assert list(mutant_tree.diagnostics) == [], (
                f"{c.original_text} -> {c.replacement_text} produced parse diagnostics"
            )


class TestOperatorSwapPairing:
    def test_swap_stays_within_same_category(self):
        # Regression guard for the "only pair within same category" rule -
        # e.g. bitwise & must become bitwise |, never logical ||.
        tree, source = parse_file(UART_PATH)
        cands = logic.operator_swap(tree, source)
        for c in cands:
            if c.original_text.strip() == "&":
                assert c.replacement_text == "|"
            if c.original_text.strip() == "&&":
                assert c.replacement_text == "||"
