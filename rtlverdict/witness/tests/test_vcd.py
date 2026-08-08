import subprocess
from pathlib import Path

import pytest

from rtlverdict import env
from rtlverdict.witness.diff_traces import diff_traces
from rtlverdict.witness.run_test import run_test
from rtlverdict.witness.vcd import VCDTrace

FSM_DIR = Path("designs/fsm")


def _needs_toolchain():
    import os

    return not os.environ.get("RTLVERDICT_OSS_CAD_ROOT")


@pytest.fixture(scope="module")
def fsm_vcd(tmp_path_factory):
    if _needs_toolchain():
        pytest.skip("requires RTLVERDICT_OSS_CAD_ROOT")
    subprocess_env = env.build_subprocess_env()
    import shutil

    iverilog = shutil.which("iverilog.exe", path=subprocess_env["PATH"])
    vvp = shutil.which("vvp.exe", path=subprocess_env["PATH"])
    out_dir = tmp_path_factory.mktemp("fsm_vcd")
    vvp_bin = out_dir / "sim.vvp"
    subprocess.run(
        [iverilog, "-g2005", "-o", str(vvp_bin), "designs/fsm/fsm.v", "designs/fsm/tb_fsm.v"],
        env=subprocess_env,
        check=True,
        capture_output=True,
    )
    subprocess.run([vvp, str(vvp_bin), "+vcd"], env=subprocess_env, cwd=out_dir, capture_output=True)
    return out_dir / "tb_fsm.vcd"


class TestVCDTrace:
    def test_known_signal_values_at_known_times(self, fsm_vcd):
        trace = VCDTrace(str(fsm_vcd))
        # golden fsm: busy asserts one cycle after `start`, clears after FINISH.
        # These times/values were independently confirmed during development
        # (Section 0-equivalent smoke test for witness) against the raw VCD.
        assert trace.value_at("tb_fsm.dut.busy", 0) == "x"
        assert trace.value_at("tb_fsm.dut.busy", 25000) == "0"
        assert trace.value_at("tb_fsm.dut.busy", 40000) == "1"
        assert trace.value_at("tb_fsm.dut.busy", 100000) == "0"

    def test_transitions_returns_only_actual_changes(self, fsm_vcd):
        trace = VCDTrace(str(fsm_vcd))
        t = trace.transitions("tb_fsm.dut.busy", 0, 120000)
        values = [v for _, v in t]
        assert values == ["x", "0", "1", "0"]  # no duplicate consecutive values

    def test_resolve_by_suffix(self, fsm_vcd):
        trace = VCDTrace(str(fsm_vcd))
        # "busy" alone is genuinely ambiguous here (tb_fsm.busy AND
        # tb_fsm.dut.busy both exist, same underlying signal through a
        # direct port connection) - the resolver correctly refuses to guess.
        assert trace.value_at("dut.busy", 40000) == trace.value_at("tb_fsm.dut.busy", 40000)

    def test_ambiguous_suffix_raises_instead_of_guessing(self, fsm_vcd):
        trace = VCDTrace(str(fsm_vcd))
        with pytest.raises(KeyError, match="ambiguous"):
            trace.value_at("busy", 40000)


class TestDiffTraces:
    def test_identical_traces_have_no_divergence(self, fsm_vcd):
        div = diff_traces(str(fsm_vcd), str(fsm_vcd), clock_period=10000, scope_filter="dut")
        assert div is None


class TestRunTest:
    def test_keep_task_shows_real_divergence(self, tmp_path):
        if _needs_toolchain():
            pytest.skip("requires RTLVERDICT_OSS_CAD_ROOT")
        import json

        tasks = json.load(open("benchmarks/corpus_v1/tasks.json"))
        keep_fsm = next(
            t for t in tasks if t["design"] == "fsm" and t["forge_decision"] == "KEEP"
        )
        r = run_test(
            "designs/fsm/fsm.v",
            keep_fsm["mutant_path"],
            "designs/fsm/tb_fsm.v",
            clock_period=10000,
            work_dir=str(tmp_path),
        )
        assert r.pass_ is False
        assert r.first_divergence is not None
        assert r.first_divergence["signal"] in ("busy", "done")
