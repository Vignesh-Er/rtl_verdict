"""Hand-rolled VCD parser - no gtkwave, no third-party VCD library, per the
brief. Format confirmed against real sby- and Icarus-generated VCDs during
toolchain verification: `$var <type> <width> <id> <name> $end` declarations
nested in `$scope module NAME $end ... $upscope $end` blocks, followed by
`#<time>` timestamps and value-change lines (`b<binary> <id>` for multi-bit,
`<bit><id>` with no separator for 1-bit scalars).
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass

_VAR_RE = re.compile(r"\$var \S+ (\d+) (\S+) (\S+)")
_BUS_RE = re.compile(r"^b([01xz]+) (\S+)$")
_SCALAR_RE = re.compile(r"^([01xz])(\S+)$")


@dataclass
class SignalInfo:
    id: str
    width: int
    scope_path: str  # dot-joined scope hierarchy, not including signal name
    name: str

    @property
    def full_path(self) -> str:
        return f"{self.scope_path}.{self.name}" if self.scope_path else self.name


class VCDTrace:
    """Loads an entire VCD into memory: a signal-id -> SignalInfo map, and
    per-signal-id sorted (time, value) change lists. Fine for the corpus
    scale this project targets (Tier A designs, hundreds of cycles);
    revisit with streaming parsing if Tier B traces ever need this.
    """

    def __init__(self, path: str):
        self.path = path
        self._id_to_info: dict[str, list[SignalInfo]] = {}
        self._path_to_id: dict[str, str] = {}
        self._changes: dict[str, list[tuple[int, str]]] = {}
        self._parse()

    def _parse(self) -> None:
        with open(self.path) as f:
            lines = f.readlines()

        scope_stack: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("$scope"):
                scope_stack.append(line.split()[2])
            elif line.startswith("$upscope"):
                scope_stack.pop()
            elif line.startswith("$var"):
                m = _VAR_RE.match(line)
                if m:
                    width, vid, name = m.groups()
                    info = SignalInfo(
                        id=vid, width=int(width), scope_path=".".join(scope_stack), name=name
                    )
                    self._id_to_info.setdefault(vid, []).append(info)
                    self._path_to_id[info.full_path] = vid
                    self._changes.setdefault(vid, [])
            elif line.startswith("$enddefinitions"):
                i += 1
                break
            i += 1

        time = 0
        pending: dict[str, str] = {}

        def flush(t: int) -> None:
            for vid, val in pending.items():
                changes = self._changes[vid]
                if not changes or changes[-1][1] != val:
                    changes.append((t, val))
            pending.clear()

        for line in lines[i:]:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("#"):
                flush(time)
                time = int(line[1:])
                continue
            m = _BUS_RE.match(line)
            if m:
                val, vid = m.groups()
            else:
                m = _SCALAR_RE.match(line)
                if not m:
                    continue
                val, vid = m.groups()
            if vid in self._changes:
                pending[vid] = val
        flush(time)
        self.end_time = time

    def signals(self) -> list[str]:
        return sorted(self._path_to_id.keys())

    def _resolve(self, signal_path: str) -> str:
        if signal_path in self._path_to_id:
            return self._path_to_id[signal_path]
        # allow matching by suffix (e.g. "busy" matching "tb_fsm.dut.busy")
        matches = [p for p in self._path_to_id if p.endswith("." + signal_path) or p == signal_path]
        if len(matches) == 1:
            return self._path_to_id[matches[0]]
        if not matches:
            raise KeyError(f"no signal matches {signal_path!r} in {self.path}")
        raise KeyError(f"ambiguous signal {signal_path!r}: matches {matches}")

    def value_at(self, signal_path: str, t: int) -> str:
        vid = self._resolve(signal_path)
        changes = self._changes[vid]
        if not changes or t < changes[0][0]:
            return "x"
        times = [c[0] for c in changes]
        idx = bisect_right(times, t) - 1
        return changes[idx][1]

    def transitions(self, signal_path: str, t0: int, t1: int) -> list[tuple[int, str]]:
        vid = self._resolve(signal_path)
        return [(t, v) for t, v in self._changes[vid] if t0 <= t <= t1]

    def window(self, signal_paths: list[str], t_center: int, k_steps: int, step: int) -> list[dict]:
        """Compact table: one row per sampled time, one column per signal.
        `step` is the caller-provided sample spacing (e.g. the clock
        period) since a VCD alone doesn't know what a "cycle" is.
        """
        t0 = t_center - k_steps * step
        t1 = t_center + k_steps * step
        rows = []
        t = t0
        while t <= t1:
            row = {"t": t}
            for sp in signal_paths:
                row[sp] = self.value_at(sp, t)
            rows.append(row)
            t += step
        return rows
