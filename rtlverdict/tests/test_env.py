import os

import pytest

from rtlverdict.env import to_msys_path, run_doctor, oss_cad_root


class TestToMsysPath:
    def test_drive_letter(self):
        assert to_msys_path(r"E:\Hackathon\claude_proj") == "/e/Hackathon/claude_proj"

    def test_lowercase_drive_letter(self):
        assert to_msys_path(r"c:\Users\vigne") == "/c/Users/vigne"

    def test_root_of_drive(self):
        assert to_msys_path("C:\\") == "/c/"

    def test_already_posix(self):
        assert to_msys_path("/e/Hackathon/claude_proj") == "/e/Hackathon/claude_proj"

    def test_forward_slashes_with_drive(self):
        assert to_msys_path("E:/Hackathon/claude_proj") == "/e/Hackathon/claude_proj"

    def test_mixed_separators(self):
        assert to_msys_path(r"E:\Hackathon/claude_proj\rtlverdict") == "/e/Hackathon/claude_proj/rtlverdict"

    def test_path_with_spaces(self):
        assert to_msys_path(r"C:\Program Files\Git") == "/c/Program Files/Git"


class TestDoctor:
    def test_oss_cad_root_raises_without_env_var(self, monkeypatch):
        monkeypatch.delenv("RTLVERDICT_OSS_CAD_ROOT", raising=False)
        with pytest.raises(RuntimeError, match="RTLVERDICT_OSS_CAD_ROOT"):
            oss_cad_root()

    @pytest.mark.skipif(
        not os.environ.get("RTLVERDICT_OSS_CAD_ROOT"),
        reason="requires a real oss-cad-suite install for this integration check",
    )
    def test_doctor_finds_all_tools_on_this_machine(self):
        report = run_doctor()
        missing = [t.name for t in report.tools if not t.found]
        assert not missing, f"tools not found: {missing}"
