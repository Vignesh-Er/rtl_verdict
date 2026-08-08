from rtlverdict.witness.coi import cone_of_influence

FSM_SOURCE = open("designs/fsm/fsm.v").read()
UART_SOURCE = open("designs/uart/uart.v").read()


class TestConeOfInfluence:
    def test_busy_cone_contains_its_own_assignments(self):
        coi = {c["line"] for c in cone_of_influence(FSM_SOURCE, "busy")}
        # every line where fsm.v directly assigns busy must be in its own cone
        assert 16 in coi  # busy <= 1'b0 (reset)
        assert 22 in coi  # busy <= 1'b0 (IDLE)
        assert 26 in coi  # busy <= 1'b1 (start)
        assert 37 in coi  # busy <= 1'b0 (FINISH)

    def test_condition_gating_an_assignment_is_in_the_cone(self):
        # Regression test for a real bug: a condition that gates whether an
        # assignment executes (e.g. `if (bit_index == 3'd7)` controlling
        # whether bit_index increments in the else branch) must appear in
        # the target signal's cone even though the condition line itself
        # never assigns anything. First found via the containment gate
        # dropping to 90% (uart_operator_swap_000, root_cause on the
        # condition line itself), not by inspection.
        coi = {c["line"] for c in cone_of_influence(UART_SOURCE, "bit_index")}
        assert 38 in coi  # if (bit_index == 3'd7) - gates line 41's increment
        assert 41 in coi  # bit_index <= bit_index + 3'd1

    def test_cone_does_not_include_unrelated_signal_definitions(self):
        # sclk/cs_n/mosi don't exist in uart.v; use a signal genuinely
        # unrelated to bit_index within the same design instead: `tx` is
        # written independently and doesn't feed bit_index's own cone.
        coi = {c["line"] for c in cone_of_influence(UART_SOURCE, "bit_index")}
        assert 32 not in coi  # tx <= 1'b0 (START_BIT) - not part of bit_index's cone


class TestContainment:
    """The real gate: for every KEEP task with a known diverging signal, the
    recorded root_cause_line must fall inside cone_of_influence(signal).
    Hardcoded here from the real corpus_v1 + witness run_test results
    (scratch_verify/run_coi_gate.py) rather than re-running simulation in
    every test invocation - this is the regression-test version of that
    gate, not a replacement for re-measuring it at corpus scale.
    """

    KNOWN_CASES = [
        (FSM_SOURCE, "done", 19),
        (FSM_SOURCE, "busy", 22),
        (FSM_SOURCE, "busy", 26),
        (UART_SOURCE, "bit_index", 38),
        (UART_SOURCE, "bit_index", 41),
        (UART_SOURCE, "tx_busy", 20),
        (UART_SOURCE, "tx", 24),
        (UART_SOURCE, "tx_busy", 28),
        (UART_SOURCE, "tx", 32),
        (UART_SOURCE, "bit_index", 34),
    ]

    def test_all_known_cases_are_contained(self):
        failures = []
        for source, signal, root_cause_line in self.KNOWN_CASES:
            coi = {c["line"] for c in cone_of_influence(source, signal)}
            if root_cause_line not in coi:
                failures.append((signal, root_cause_line))
        assert not failures, f"containment gate failures: {failures}"
