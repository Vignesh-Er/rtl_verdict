import os
import subprocess
from pathlib import Path

import pytest

from rtlverdict import env
from rtlverdict.witness.suspect_rank import suspect_rank


def _needs_toolchain():
    return not os.environ.get("RTLVERDICT_OSS_CAD_ROOT")


@pytest.fixture(scope="module")
def fsm_mutant_vcd(tmp_path_factory):
    if _needs_toolchain():
        pytest.skip("requires RTLVERDICT_OSS_CAD_ROOT")
    import shutil

    subprocess_env = env.build_subprocess_env()
    iverilog = shutil.which("iverilog.exe", path=subprocess_env["PATH"])
    vvp = shutil.which("vvp.exe", path=subprocess_env["PATH"])
    out_dir = tmp_path_factory.mktemp("fsm_mutant_vcd")
    vvp_bin = out_dir / "sim.vvp"
    subprocess.run(
        [
            iverilog,
            "-g2005",
            "-o",
            str(vvp_bin),
            "designs/fsm/fsm_mutant_shallow.v",
            "designs/fsm/tb_fsm.v",
        ],
        env=subprocess_env,
        check=True,
        capture_output=True,
    )
    subprocess.run([vvp, str(vvp_bin), "+vcd"], env=subprocess_env, cwd=out_dir, capture_output=True)
    return out_dir / "tb_fsm.vcd"


class TestSuspectRank:
    def test_root_cause_is_in_top_ranked_group(self, fsm_mutant_vcd):
        source = open("designs/fsm/fsm.v").read()
        # fsm_mutant_shallow.v's known bug is an off-by-one at line 30
        # (RUN state exit condition), observable through `busy` staying
        # asserted one cycle too long - divergence around t=45000 in this
        # testbench's timing (2-cycle reset hold + start pulse).
        results = suspect_rank(
            source, "busy", str(fsm_mutant_vcd), divergence_time=45000,
            scope_prefix="tb_fsm.dut", file_name="fsm.v",
        )
        assert results, "expected at least one suspect"
        top_score = results[0].score
        top_lines = {r.line for r in results if r.score == top_score}
        # root cause (busy's own definitions, lines 13-37) should be
        # reachable in the tied top-scoring group, not absent entirely.
        assert top_lines & {13, 16, 20, 22, 23, 26, 37}
