# Demo script (`~90s`)

Rehearsed end-to-end once on the reference machine (Windows 11, this
repo's own toolchain) before being written down — every command below
and every number in "expected output" is what actually happened on that
rehearsal run, not a guess. Timings are per-step wall-clock from that
rehearsal, rounded up slightly for a live presenter's margin.

Prerequisites (do this before the audience is watching, not during):
`RTLVERDICT_OSS_CAD_ROOT` and `RTLVERDICT_TOOL_SHIMS` set, a terminal
open in the repo root, and `docs/index.html` already built
(`python scripts/build_dashboard.py` — it takes about a minute, too
long to run live, see step 3's fallback).

---

## Step 1 — toolchain check (~5s)

**Say:** "Every tool this needs is open source — no commercial EDA, no
FPGA. Here's the live check."

**Run:**
```
python -m rtlverdict.doctor
```

**Expect:** 12 rows, all `OK`, ending in `All 12 required tools OK.`
Rehearsed runtime: under 1 second.

**Fallback (a tool shows red):** Don't debug it live. Say "that's
exactly what this command is for — a real remedy, not a guess" and read
the one-line remedy in that row out loud, then move straight to Step 2
anyway (`make verify` will fail fast and visibly if the toolchain is
genuinely broken, which is itself an honest demo of the fail-loud
design). If it's a dead machine entirely, skip to Step 3 and open the
already-built `docs/index.html` — every number there was generated
ahead of time, not live.

## Step 2 — prove the formal gate discriminates (~15s)

**Say:** "This re-runs the real formal ladder — not a mock — on a fixed
task subset, plus one genuinely correct fix and one genuinely wrong fix,
and checks the gate tells them apart."

**Run:**
```
make verify
```

**Expect:** 10 `[forge]` lines all ending `REFUTED (divergence_cycle=…)`,
then:
```
[C2] fsm_constant_perturbation_005: final_verdict=PLAUSIBLE (…)
[C3] uart_constant_perturbation_005: final_verdict=REFUTED (…)

Total wall-clock: …s (budget: 300s)

============================================================
VERIFY: PASS - 10 forge checks + C2 + C3 all match benchmarks\verify_golden.json
============================================================
```
Rehearsed runtime: 10.6s internal / 13.1s total wall-clock (`time make verify`).
**Point at the C2/C3 lines specifically** — C2 (a real fix) comes back
`PLAUSIBLE`, C3 (a real wrong fix, a different task's mutant resubmitted
as the "fix") comes back `REFUTED`. That's the whole thesis in two lines.

**Fallback (slow machine, first-run tool warmup, or antivirus scanning
new binaries):** `make verify`'s own budget is 5 minutes; a live run
running long is not a failure, just less snappy than rehearsed. Keep
talking — walk through what it's doing (bullet list above) — or, if
truly stuck, `Ctrl+C` and say "here's what this looked like when I ran
it earlier" while showing `results/verify_run_report.json` (committed,
real, timestamped) and `results/verdict_ladder_validation.md`.

## Step 3 — open the dashboard (~10s)

**Say:** "Everything above, plus every mutant in the corpus, browsable
in one offline file — no server, no build step."

**Run (PowerShell):**
```
start docs\index.html
```
(or just double-click `docs/index.html` in File Explorer — it's a
plain file, `file://` works identically to serving it)

**Expect:** Opens in the default browser. Header shows three large
numbers (13.6%–72.2%, 49.1%, 95.2%) under the tagline.

**Fallback (nothing opens / no default browser configured):** Drag
`docs/index.html` directly into any open browser window, or run
`start chrome docs\index.html` / `start msedge docs\index.html`
explicitly. If genuinely no browser is available, this is the point to
fall back to the static figures in `results/figures/` and the
underlying `.md` reports instead — the dashboard is a browser, not a
new source of numbers, so nothing is lost, only the interactivity.

## Step 4 — the verdict-ladder panel (~20s)

**Say:** "Does the formal gate actually prove anything, or just run? Here's the direct evidence — including the two verdict classes this project can never produce, shown on purpose instead of hidden."

**Do:** Scroll to "Does the formal gate actually prove anything?" Point
at the callout: **"PROVEN-BMC(k) = no counterexample found up to depth
k. Not a proof."** Then point at the table: 4 conditions, all `PASS`,
then the two greyed-out rows below them — `PROVEN-BMC` and
`PROVEN-UNBOUNDED`, both marked "never," with the reason inline.

**Fallback (JS didn't execute — very old browser, or opened as plain
text):** Read the same content directly from
`results/verdict_ladder_validation.md`'s "Answers, up front" section —
identical numbers, just not filterable.

## Step 5 — inspect one real mutant (~30s)

**Say:** "Every one of the 171 mutants is in here, with its actual
diff, its formal verdict, and a real backward slice — not summary
stats, the artifact itself."

**Do:** In "Task explorer," set the **Verdict** filter to `SILENT` (a
real bug the testbench misses — the project's own headline finding).
Click any row. In the side panel: point at **First divergence** (a real
signal name and cycle, from an actual simulation run at build time),
then **COI backward slice** (the chips), then scroll to **Mutant diff**
(a real unified diff, red/green colored).

**Fallback (side panel stays empty after a click):** Click a different
row once more — first-click focus issues in some browsers occasionally
eat the first event. If it's still empty, open the browser's console
(F12) for the actual error rather than guessing, or fall back to
`results/silent_bugs.md` for the same SILENT-class numbers without the
per-task drill-down.

---

## Closing line (~10s)

**Say:** "Nothing here is a mock or a projection — the toolchain check,
the formal discrimination test, and every mutant in the browser were
all generated by these exact scripts, and `make verify` reproduces the
formal claims in under 15 seconds, offline, on any machine with the
same open-source toolchain."

---

## What this demo deliberately does NOT claim

Per `README.md`'s Limitations, stated here too so it's never implied by
omission during a live walkthrough: no live agent ran (`results/agent_pilot.md`
is a plumbing test); the formal ladder is BMC-bounded, not an unbounded
proof; the coverage-vs-silent-bug relationship was investigated and
withdrawn; the COI containment figure is historical and not quoted
here. If asked live whether an AI agent actually fixed any of these
bugs: no, not yet — that's explicitly the next step, honestly labeled
as not done, not glossed over.
