"""scripts/build_dashboard.py -> docs/index.html

Builds ONE self-contained, offline-capable dashboard: every number, every
task record, every mutant diff, every COI slice, all 4 figures (as inline
SVG), and the verdict-ladder validation matrix are computed/read HERE, at
build time, and inlined into the HTML as a single JSON blob plus literal
SVG markup. No React, no npm, no build step for a viewer, no runtime CDN
fetch - opening the file directly (file://) or serving it from GitHub
Pages must behave identically, since nothing loads at view time that
wasn't already embedded.

Run: python scripts/build_dashboard.py  (from repo root, toolchain env
vars set - it runs real simulations for first-divergence detection and
real static analysis for COI slices, not just JSON reformatting).
"""

from __future__ import annotations

import difflib
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from rtlverdict import env  # noqa: E402
from rtlverdict.witness.coi import cone_of_influence  # noqa: E402
from rtlverdict.witness.run_test import run_test  # noqa: E402
from rtlverdict.agent.run_smoke import DESIGN_INFO  # noqa: E402
from chart_palette import CATEGORICAL, CHROME, VERDICT_COLORS, VERDICT_ORDER  # noqa: E402

CORPUS_FILES = [
    REPO_ROOT / "benchmarks" / "corpus_v2" / "tasks.json",
    REPO_ROOT / "benchmarks" / "corpus_v2_fifo_addition" / "tasks.json",
]
FIGURES = [
    "fig1_verdict_composition",
    "fig2_silent_rate_vs_coverage",
    "fig3_equivalence_by_operator",
    "fig4_divergence_depth_histogram",
]
OUT_PATH = REPO_ROOT / "docs" / "index.html"

# Patch-path verdict taxonomy is not covered by chart_palette.py (which
# only defines forge_decision colors) - extended here, same semantic
# logic (status color = confidence level, muted = deliberately not a
# status claim), documented inline rather than silently invented:
#   PLAUSIBLE = muted, same treatment as QUARANTINE - a bounded pass is
#     deliberately NOT colored "good", so it never reads as more certain
#     than it is (see README's Verdict taxonomy section).
#   REFUTED = critical - a real counterexample against a proposed fix.
#   INVALID-PATCH / NO-PATCH = warning - never reached a formal claim.
PATCH_VERDICT_COLORS = {
    "PLAUSIBLE": "#898781",
    "REFUTED": VERDICT_COLORS["SILENT"],
    "INVALID-PATCH": VERDICT_COLORS["ERROR"],
    "NO-PATCH": VERDICT_COLORS["ERROR"],
}


def _load_all_tasks() -> list[dict]:
    tasks = []
    for p in CORPUS_FILES:
        tasks.extend(json.loads(p.read_text()))
    return tasks


def _unified_diff(golden_path: str, mutant_path: str, design: str) -> str:
    # splitlines() WITHOUT keepends, paired with lineterm="" - each yielded
    # diff line (content or control) carries no newline of its own, so a
    # single "\n".join() adds exactly one separator per line. Mixing
    # keepends=True input with "\n".join() double-spaces every content
    # line (found by actually reading the generated diff output, not by
    # inspection - every line had a blank line after it).
    golden_lines = Path(golden_path).read_text().splitlines()
    mutant_lines = Path(mutant_path).read_text().splitlines()
    diff = difflib.unified_diff(
        golden_lines, mutant_lines,
        fromfile=f"golden/{design}.v", tofile=f"mutant/{Path(mutant_path).name}",
        lineterm="",
    )
    return "\n".join(diff)


def _build_task_record(task: dict, idx: int, total: int) -> dict:
    design = task["design"]
    top_module, reset_signal, reset_active_low, clock_period = DESIGN_INFO[design]
    testbench_path = REPO_ROOT / "designs" / design / f"tb_{design}.v"

    # ERROR-decision tasks never had a mutant file written at all (forge's
    # fidelity guard rejected the candidate before ever writing one to
    # disk - mutant_path is "" for these, never a real path) - nothing to
    # diff or simulate for them.
    diff_text = None
    if task["mutant_path"]:
        diff_text = _unified_diff(task["golden_path"], task["mutant_path"], design)

    first_divergence = None
    coi_slice = None
    if task["error"] is None:
        try:
            r = run_test(
                task["golden_path"], task["mutant_path"], str(testbench_path),
                clock_period, str(REPO_ROOT / "scratch_verify" / "dash_build" / task["task_id"]),
            )
            first_divergence = r.first_divergence
        except Exception as e:  # noqa: BLE001 - a handful of edge cases must never abort the whole build
            first_divergence = {"error": f"{type(e).__name__}: could not compute (build-time, non-fatal)"}

        signal = (first_divergence or {}).get("signal") if isinstance(first_divergence, dict) else None
        if signal:
            try:
                golden_source = Path(task["golden_path"]).read_text()
                coi_slice = cone_of_influence(golden_source, signal, f"{design}.v")
            except Exception as e:  # noqa: BLE001
                coi_slice = {"error": f"{type(e).__name__}"}

    print(f"  [{idx + 1}/{total}] {task['task_id']} ({design}, {task['forge_decision']})")

    op_short = task["operator"].split(".")[-1]
    return {
        "task_id": task["task_id"],
        "design": design,
        "operator": op_short,
        "bug_class": task["bug_class"],
        "forge_decision": task["forge_decision"],
        "equivalence_to_golden": task["equivalence_to_golden"],
        "sim_golden": task["sim_golden"],
        "sim_mutant": task["sim_mutant"],
        "divergence_cycle": task["divergence_cycle"],
        "formal_k": task["formal_k"],
        "formal_tier": task["formal_tier"],
        "formal_engine": task["formal_engine"],
        "formal_runtime_s": task["formal_runtime_s"],
        "root_cause_line": task["root_cause_line"],
        "discard_reason": task["discard_reason"],
        "error": task["error"],
        "diff": diff_text,
        "first_divergence": first_divergence,
        "coi_slice": coi_slice,
    }


def _load_figures() -> dict[str, str]:
    out = {}
    for name in FIGURES:
        svg_path = REPO_ROOT / "results" / "figures" / f"{name}.svg"
        out[name] = svg_path.read_text(encoding="utf-8")
    return out


def _load_verdict_ladder() -> dict:
    path = REPO_ROOT / "results" / "verdict_ladder_validation_report.json"
    return json.loads(path.read_text())


def build_data() -> dict:
    env.sweep_orphaned_solvers()
    stats = json.loads((REPO_ROOT / "results" / "corpus_stats.json").read_text())
    tasks = _load_all_tasks()

    print(f"Building per-task records for {len(tasks)} tasks (real simulation + COI per task)...")
    t0 = time.time()
    task_records = [_build_task_record(t, i, len(tasks)) for i, t in enumerate(tasks)]
    print(f"Done in {time.time() - t0:.1f}s")

    return {
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corpus_stats": stats,
        "tasks": task_records,
        "figures": _load_figures(),
        "verdict_ladder": _load_verdict_ladder(),
        "palette": {
            "verdict_colors": VERDICT_COLORS,
            "verdict_order": VERDICT_ORDER,
            "patch_verdict_colors": PATCH_VERDICT_COLORS,
            "chrome": CHROME,
            "categorical": CATEGORICAL,
        },
    }


_CSS = """
:root {
  --sp-1: 8px; --sp-2: 16px; --sp-3: 24px; --sp-4: 32px; --sp-5: 40px; --sp-6: 48px;
  --max-w: 1100px;
  --surface: #fcfcfb;
  --page: #f9f9f7;
  --ink: #0b0b0b;
  --ink-2: #52514e;
  --ink-muted: #898781;
  --gridline: #e1e0d9;
  --baseline: #c3c2b7;
  --accent: #2a78d6;
  --accent-ink: #ffffff;
  --v-keep: #0ca30c;
  --v-silent: #d03b3b;
  --v-error: #fab219;
  --v-quarantine: #898781;
  --v-plausible: #898781;
  --v-refuted: #d03b3b;
  --v-invalid: #fab219;
  --font-prose: system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, "SF Mono", Consolas, "Liberation Mono", monospace;
  --dur: 150ms;
}
* { box-sizing: border-box; }
html { color-scheme: light; }
html, body { overflow-x: hidden; }  /* backstop: wide content must scroll in its own container, never the page */
body {
  margin: 0;
  background: var(--page);
  color: var(--ink);
  font-family: var(--font-prose);
  line-height: 1.6;
  font-size: 16px;
}
code, pre, .mono, .task-id, .verdict-badge, .signal {
  font-family: var(--font-mono);
}
/* Long unbreakable inline tokens (file paths like results/corpus_stats.json,
   no spaces to wrap at) otherwise force their own line - and the whole page,
   since nothing contains it - wider than the viewport on narrow screens.
   Found by actually rendering at a phone width and looking, not by
   inspection: everything past the header appeared cut off, and the true
   cause turned out to be inline <code> spans, not the tables (which already
   had their own overflow-x:auto). */
code, .wrap p, .wrap li, .wrap dd, .section-note, .tagline {
  overflow-wrap: break-word;
  word-break: break-word;
}
.wrap { max-width: var(--max-w); margin: 0 auto; padding: 0 var(--sp-3); overflow-wrap: break-word; }
a { color: var(--accent); }
h1, h2, h3 { line-height: 1.25; margin: 0 0 var(--sp-2) 0; }
h1 { font-size: 1.7rem; }
h2 { font-size: 1.25rem; margin-top: 0; }
h3 { font-size: 1rem; }
p { margin: 0 0 var(--sp-2) 0; }

header.hero {
  background: var(--surface);
  border-bottom: 1px solid var(--gridline);
  padding: var(--sp-4) 0 var(--sp-4) 0;
}
header.hero .tagline { color: var(--ink-2); font-size: 1.05rem; margin-bottom: var(--sp-3); }
.finding-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--sp-3);
}
.finding {
  background: var(--page);
  border: 1px solid var(--gridline);
  border-radius: 6px;
  padding: var(--sp-3);
}
.finding .big { font-size: 2rem; font-weight: 700; font-family: var(--font-mono); color: var(--ink); }
.finding .label { color: var(--ink-2); font-size: 0.9rem; margin-top: var(--sp-1); }
.finding .caveat { color: var(--ink-muted); font-size: 0.78rem; margin-top: var(--sp-1); }

section { padding: var(--sp-5) 0; }
section.alt { background: var(--surface); border-top: 1px solid var(--gridline); border-bottom: 1px solid var(--gridline); }
.section-note { color: var(--ink-2); font-size: 0.92rem; }

.callout {
  background: var(--page);
  border: 1px solid var(--baseline);
  border-left: 4px solid var(--accent);
  border-radius: 4px;
  padding: var(--sp-2) var(--sp-3);
  margin: var(--sp-2) 0 var(--sp-3) 0;
  overflow-wrap: break-word;
  font-family: var(--font-mono);
  font-size: 0.95rem;
}

table { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
#ladder-table-wrap { overflow-x: auto; border: 1px solid var(--gridline); border-radius: 6px; background: var(--surface); }
#ladder-table-wrap table { min-width: 640px; margin: 0; }
th, td { text-align: left; padding: var(--sp-1) var(--sp-2); border-bottom: 1px solid var(--gridline); vertical-align: top; }
th { color: var(--ink-2); font-weight: 600; font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.02em; }
tr.unreachable { opacity: 0.65; }
tr.unreachable td { font-style: italic; color: var(--ink-2); }

.badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 999px;
  font-family: var(--font-mono);
  font-size: 0.78rem;
  font-weight: 600;
  color: #fff;
  white-space: nowrap;
}
.badge.pass-yes { background: var(--v-keep); }
.badge.pass-unreachable { background: transparent; color: var(--ink-muted); border: 1px dashed var(--ink-muted); }

.filters {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin-bottom: var(--sp-3);
  align-items: center;
}
.filters label { font-size: 0.85rem; color: var(--ink-2); display: flex; flex-direction: column; gap: 4px; }
.filters select, .filters input {
  font-family: var(--font-prose);
  font-size: 0.9rem;
  padding: 6px 8px;
  border: 1px solid var(--baseline);
  border-radius: 4px;
  background: var(--surface);
  color: var(--ink);
}
.filters select:focus, .filters input:focus, button:focus, .task-row:focus {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
#result-count { color: var(--ink-muted); font-size: 0.85rem; }

.explorer-grid {
  display: grid;
  grid-template-columns: 1.3fr 1fr;
  gap: var(--sp-3);
  align-items: start;
}
/* Own scroll container, same pattern as #ladder-table-wrap: at narrow
   widths a fixed-percentage layout forced short header words ("verdict",
   "depth") to wrap letter-by-letter instead of stay on one line - found by
   actually rendering at a real 390px mobile width (Chrome's headless
   --window-size has an OS-level ~500px floor on this machine, so a proper
   CDP device-metrics-override emulation was needed to catch this at all).
   table-layout:auto + white-space:nowrap on headers + a sane min-width
   lets the table scroll as a whole on narrow screens instead of mangling
   its own headers. */
#table-scroll { max-height: 560px; overflow: auto; border: 1px solid var(--gridline); border-radius: 6px; background: var(--surface); }
#table-scroll table { margin: 0; min-width: 480px; }
#table-scroll th { white-space: nowrap; }
#table-scroll td:nth-child(1) { max-width: 220px; }
#table-scroll td:nth-child(3) { max-width: 160px; }
#table-scroll td.truncate { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
#table-scroll thead th { position: sticky; top: 0; background: var(--surface); z-index: 1; }
.task-row { cursor: pointer; transition: background var(--dur) ease-out; }
.task-row:hover, .task-row.selected { background: var(--page); }
.task-row.selected { box-shadow: inset 3px 0 0 var(--accent); }

#side-panel {
  position: sticky;
  top: var(--sp-2);
  background: var(--surface);
  border: 1px solid var(--gridline);
  border-radius: 6px;
  padding: var(--sp-3);
  max-height: 640px;
  overflow-y: auto;
}
#side-panel .placeholder { color: var(--ink-muted); font-style: italic; }
#side-panel dl { display: grid; grid-template-columns: auto 1fr; gap: 4px var(--sp-2); margin: var(--sp-2) 0; font-size: 0.88rem; }
#side-panel dt { color: var(--ink-2); }
#side-panel dd { margin: 0; font-family: var(--font-mono); }
#side-panel pre {
  background: var(--page);
  border: 1px solid var(--gridline);
  border-radius: 4px;
  padding: var(--sp-2);
  overflow-x: auto;
  font-size: 0.82rem;
  line-height: 1.5;
}
.diff-add { color: #0ca30c; }
.diff-del { color: #d03b3b; }
.coi-lines { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 4px; }
.coi-lines .chip {
  font-family: var(--font-mono);
  font-size: 0.78rem;
  background: var(--page);
  border: 1px solid var(--gridline);
  border-radius: 4px;
  padding: 1px 6px;
}

.figures-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-4); }
.figures-grid figure { margin: 0; }
.figures-grid svg { width: 100%; height: auto; display: block; border: 1px solid var(--gridline); border-radius: 6px; background: #fcfcfb; }
.figures-grid figcaption { color: var(--ink-muted); font-size: 0.8rem; margin-top: var(--sp-1); }

footer { padding: var(--sp-4) 0 var(--sp-6) 0; color: var(--ink-muted); font-size: 0.82rem; }
footer .tool-list { font-family: var(--font-mono); font-size: 0.78rem; line-height: 1.8; word-break: break-word; }

@media (max-width: 800px) {
  .finding-grid { grid-template-columns: 1fr; }
  .explorer-grid { grid-template-columns: 1fr; }
  #side-panel { position: static; max-height: none; }
  .figures-grid { grid-template-columns: 1fr; }
  #table-scroll { max-height: 400px; }
}

@media (prefers-reduced-motion: reduce) {
  * { transition: none !important; animation: none !important; }
}
"""


def _render_verdict_ladder_static_rows() -> str:
    """The two classes this project can never surface on the patch path -
    hardcoded here (not derived from the JSON blob) because their absence
    from any run record is exactly the point being displayed; a row that
    only appears when data exists would silently omit them again, the
    same failure engineering_log.md episode 12 documents."""
    return """
      <tr class="unreachable">
        <td>PROVEN-BMC</td><td>as surfaced final_verdict</td>
        <td><span class="badge pass-unreachable">never &mdash; by design</span></td>
        <td colspan="2">Always remapped to <code>PLAUSIBLE</code> by
          <code>_FORMAL_TO_VERDICT</code> (<a href="../rtlverdict/agent/loop.py#L39">agent/loop.py:39</a>).
          The raw result is real and recorded internally; it is never the headline label.</td>
      </tr>
      <tr class="unreachable">
        <td>PROVEN-UNBOUNDED</td><td>any path, any caller</td>
        <td><span class="badge pass-unreachable">never &mdash; does not exist</span></td>
        <td colspan="2">Not a value <code>verdict/ladder.py</code>'s <code>VERDICTS</code> enum can
          produce yet (eqy disabled for discard decisions &mdash; see README Limitations).</td>
      </tr>"""


def render_html(data: dict) -> str:
    json_blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    figures_html = "\n".join(
        f'<figure><figcaption>{name.replace("_", " ")}</figcaption>{svg}</figure>'
        for name, svg in data["figures"].items()
    )
    prov = data["corpus_stats"]["provenance"]
    git_sha = prov["git"]["commit_sha"]
    dirty = " (dirty)" if prov["git"]["dirty"] else ""

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>rtlverdict &mdash; artifact browser</title>
<style>{_CSS}</style>
</head>
<body>

<header class="hero">
  <div class="wrap">
    <h1>rtlverdict</h1>
    <p class="tagline">&ldquo;Your testbench says PASS. Can you prove it?&rdquo; &mdash; artifact browser, not a landing page. Every number below is read from <code>results/corpus_stats.json</code> at build time.</p>
    <div class="finding-grid" id="finding-grid"></div>
  </div>
</header>

<section id="verdict-ladder-section">
  <div class="wrap">
    <h2>Does the formal gate actually prove anything?</h2>
    <p class="section-note">Four input classes through the real <code>run_task &rarr; check_patch &rarr; check_bmc</code> pipeline (stub-driven, no live agent &mdash; see <code>results/agent_pilot.md</code>), plus the two verdict classes this project can never surface on the patch path, shown here rather than silently omitted. Full accounting: <code>results/verdict_ladder_validation.md</code>.</p>
    <div class="callout">PROVEN-BMC(k) = no counterexample found up to depth k. Not a proof.</div>
    <div id="ladder-table-wrap"></div>
  </div>
</section>

<section class="alt" id="explorer-section">
  <div class="wrap">
    <h2>Task explorer</h2>
    <p class="section-note">Every generated mutant, filterable by design, operator, verdict, and divergence depth. Click a row for the mutant diff, formal verdict detail, first-divergence signal, and COI backward slice.</p>
    <div class="filters">
      <label>Design <select id="f-design"></select></label>
      <label>Operator <select id="f-operator"></select></label>
      <label>Verdict <select id="f-verdict"></select></label>
      <label>Divergence depth <select id="f-depth">
        <option value="">any</option>
        <option value="0-4">0&ndash;4</option>
        <option value="5-9">5&ndash;9</option>
        <option value="10-19">10&ndash;19</option>
        <option value="20+">20+</option>
        <option value="na">n/a</option>
      </select></label>
      <span id="result-count"></span>
    </div>
    <div class="explorer-grid">
      <div id="table-scroll">
        <table>
          <thead><tr><th>task_id</th><th>design</th><th>operator</th><th>verdict</th><th>depth</th></tr></thead>
          <tbody id="task-tbody"></tbody>
        </table>
      </div>
      <div id="side-panel"><p class="placeholder">Click a task row to inspect it.</p></div>
    </div>
  </div>
</section>

<section id="figures-section">
  <div class="wrap">
    <h2>Figures</h2>
    <div class="figures-grid">{figures_html}</div>
  </div>
</section>

<footer>
  <div class="wrap">
    <div id="footer-content"></div>
    <p>git <code>{git_sha}{dirty}</code> &middot; generated {data["generated_at_utc"]}</p>
  </div>
</footer>

<script id="rtlverdict-data" type="application/json">{json_blob}</script>
<script>
const DATA = JSON.parse(document.getElementById('rtlverdict-data').textContent);

function el(tag, attrs, children) {{
  const e = document.createElement(tag);
  if (attrs) for (const k in attrs) {{
    if (k === 'class') e.className = attrs[k];
    else if (k === 'html') e.innerHTML = attrs[k];
    else e.setAttribute(k, attrs[k]);
  }}
  (children || []).forEach(c => {{ if (c) e.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); }});
  return e;
}}

function renderFindings() {{
  const sbr = DATA.corpus_stats.silent_bug_rate;
  const ct = DATA.corpus_stats.corpus_totals;
  const ops = DATA.corpus_stats.operators;
  const bns = ops.find(o => o.name === 'blocking_nonblocking_swap');
  const quarantinePct = (100 * ct.verdicts.QUARANTINE / ct.recorded).toFixed(1);
  const grid = document.getElementById('finding-grid');
  const items = [
    [`${{sbr.range.min_pct}}%–${{sbr.range.max_pct}}%`, 'silent-bug rate range across 4 designs', `pooled once: ${{sbr.rate_pct}}% — not a stable estimate`],
    [`${{quarantinePct}}%`, `mutation candidates formally equivalent (QUARANTINE)`, `${{ct.verdicts.QUARANTINE}}/${{ct.recorded}} — not bugs at all`],
    [`${{bns.equivalent_rate_pct}}%`, '`blocking_nonblocking_swap` (= vs <=) equivalent', `${{bns.equivalent_n}}/${{bns.evaluated_n}} evaluated — largest operator class`],
  ];
  items.forEach(([big, label, caveat]) => {{
    grid.appendChild(el('div', {{class: 'finding'}}, [
      el('div', {{class: 'big'}}, [big]),
      el('div', {{class: 'label'}}, [label]),
      el('div', {{class: 'caveat'}}, [caveat]),
    ]));
  }});
}}

function renderLadder() {{
  const vl = DATA.verdict_ladder;
  const wrap = document.getElementById('ladder-table-wrap');
  const table = el('table', null, []);
  table.appendChild(el('thead', null, [el('tr', null, [
    el('th', null, ['condition']), el('th', null, ['n']), el('th', null, ['expected']),
    el('th', null, ['observed']), el('th', null, ['result']),
  ])]));
  const tbody = el('tbody', null, []);
  for (const [cond, d] of Object.entries(vl.conditions)) {{
    const observed = Object.entries(d.distribution).map(([k, v]) => `${{k}}: ${{v}}/${{d.n}}`).join(', ');
    const allMatch = Object.keys(d.distribution).length === 1 && d.distribution[d.expected_final_verdict] === d.n;
    tbody.appendChild(el('tr', null, [
      el('td', null, [cond]),
      el('td', null, [String(d.n)]),
      el('td', {{html: verdictBadge(d.expected_final_verdict)}}),
      el('td', null, [observed]),
      el('td', null, [el('span', {{class: 'badge pass-yes'}}, [allMatch ? 'PASS' : 'CHECK'])]),
    ]));
  }}
  table.appendChild(tbody);
  const staticTbody = table.querySelector('tbody');
  staticTbody.insertAdjacentHTML('beforeend', {json.dumps(_render_verdict_ladder_static_rows())});
  wrap.appendChild(table);
}}

function verdictBadge(v) {{
  const colors = Object.assign({{}}, DATA.palette.verdict_colors, DATA.palette.patch_verdict_colors);
  const color = colors[v] || '#898781';
  return `<span class="badge" style="background:${{color}}">${{v}}</span>`;
}}

let selectedRow = null;
function renderSidePanel(task) {{
  const p = document.getElementById('side-panel');
  p.innerHTML = '';
  p.appendChild(el('h3', null, [task.task_id]));
  const dl = el('dl', null, []);
  const rows = [
    ['design', task.design], ['operator', task.operator], ['bug class', task.bug_class],
    ['forge_decision', task.forge_decision], ['equivalence_to_golden', task.equivalence_to_golden],
    ['formal tier', `${{task.formal_tier}} (k=${{task.formal_k}}, ${{task.formal_engine}})`],
    ['formal runtime', task.formal_runtime_s !== null ? `${{task.formal_runtime_s}}s` : 'n/a'],
    ['sim golden / mutant', `${{task.sim_golden}} / ${{task.sim_mutant}}`],
    ['root_cause_line', String(task.root_cause_line)],
  ];
  rows.forEach(([k, v]) => {{ dl.appendChild(el('dt', null, [k])); dl.appendChild(el('dd', null, [String(v)])); }});
  p.appendChild(dl);

  if (task.error) {{
    p.appendChild(el('p', {{class: 'placeholder'}}, [`Never reached verification: ${{task.error.split('\\n')[0]}}`]));
    return;
  }}

  if (task.first_divergence && task.first_divergence.signal) {{
    const fd = task.first_divergence;
    p.appendChild(el('h3', null, ['First divergence (simulation)']));
    p.appendChild(el('p', null, [`cycle `, el('span', {{class: 'signal'}}, [String(fd.cycle)]), ` on signal `, el('span', {{class: 'signal'}}, [fd.signal]), ` — expected `, el('span', {{class: 'signal'}}, [String(fd.expected)]), `, actual `, el('span', {{class: 'signal'}}, [String(fd.actual)])]));
  }} else {{
    p.appendChild(el('p', {{class: 'placeholder'}}, ['No signal-level divergence found by simulation (consistent with a formal QUARANTINE verdict, or a divergence outside the testbench\\'s own scope).']));
  }}

  if (task.coi_slice && Array.isArray(task.coi_slice)) {{
    p.appendChild(el('h3', null, ['COI backward slice']));
    const chips = el('div', {{class: 'coi-lines'}}, []);
    task.coi_slice.forEach(l => chips.appendChild(el('span', {{class: 'chip'}}, [`L${{l.line}}`])));
    p.appendChild(chips);
  }}

  if (task.diff) {{
    p.appendChild(el('h3', null, ['Mutant diff']));
    const pre = el('pre', null, []);
    const code = el('code', null, []);
    task.diff.split('\\n').forEach(line => {{
      const span = document.createElement('span');
      span.className = line.startsWith('+') && !line.startsWith('+++') ? 'diff-add' : line.startsWith('-') && !line.startsWith('---') ? 'diff-del' : '';
      span.textContent = line + '\\n';
      code.appendChild(span);
    }});
    pre.appendChild(code);
    p.appendChild(pre);
  }}
}}

function populateFilterOptions() {{
  const designs = [...new Set(DATA.tasks.map(t => t.design))].sort();
  const operators = [...new Set(DATA.tasks.map(t => t.operator))].sort();
  const verdicts = [...new Set(DATA.tasks.map(t => t.forge_decision))].sort();
  const fill = (id, values, label) => {{
    const sel = document.getElementById(id);
    sel.appendChild(el('option', {{value: ''}}, [`all (${{label}})`]));
    values.forEach(v => sel.appendChild(el('option', {{value: v}}, [v])));
  }};
  fill('f-design', designs, 'design');
  fill('f-operator', operators, 'operator');
  fill('f-verdict', verdicts, 'verdict');
}}

function depthBucket(cycle) {{
  if (cycle === null || cycle === undefined) return 'na';
  if (cycle < 5) return '0-4';
  if (cycle < 10) return '5-9';
  if (cycle < 20) return '10-19';
  return '20+';
}}

function renderTable() {{
  const fDesign = document.getElementById('f-design').value;
  const fOperator = document.getElementById('f-operator').value;
  const fVerdict = document.getElementById('f-verdict').value;
  const fDepth = document.getElementById('f-depth').value;
  const tbody = document.getElementById('task-tbody');
  tbody.innerHTML = '';
  const filtered = DATA.tasks.filter(t =>
    (!fDesign || t.design === fDesign) &&
    (!fOperator || t.operator === fOperator) &&
    (!fVerdict || t.forge_decision === fVerdict) &&
    (!fDepth || depthBucket(t.divergence_cycle) === fDepth)
  );
  document.getElementById('result-count').textContent = `${{filtered.length}} / ${{DATA.tasks.length}} tasks`;
  filtered.forEach(t => {{
    const tr = el('tr', {{class: 'task-row', tabindex: '0'}}, [
      el('td', {{class: 'task-id truncate', title: t.task_id}}, [t.task_id]),
      el('td', {{class: 'truncate', title: t.design}}, [t.design]),
      el('td', {{class: 'truncate', title: t.operator}}, [t.operator]),
      el('td', {{html: verdictBadge(t.forge_decision)}}),
      el('td', null, [t.divergence_cycle === null ? '—' : String(t.divergence_cycle)]),
    ]);
    tr.addEventListener('click', () => {{
      if (selectedRow) selectedRow.classList.remove('selected');
      tr.classList.add('selected');
      selectedRow = tr;
      renderSidePanel(t);
    }});
    tr.addEventListener('keydown', (ev) => {{ if (ev.key === 'Enter') tr.click(); }});
    tbody.appendChild(tr);
  }});
}}

function renderFooter() {{
  const tv = DATA.corpus_stats.toolchain_versions;
  const wrap = document.getElementById('footer-content');
  const list = el('div', {{class: 'tool-list'}}, []);
  Object.entries(tv).forEach(([name, ver]) => {{
    list.appendChild(el('div', null, [`${{name}}: ${{ver}}`]));
  }});
  wrap.appendChild(list);
}}

renderFindings();
renderLadder();
populateFilterOptions();
['f-design', 'f-operator', 'f-verdict', 'f-depth'].forEach(id => document.getElementById(id).addEventListener('change', renderTable));
renderTable();
renderFooter();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    data = build_data()
    print(f"Assembled {len(json.dumps(data))} bytes of embedded data.")
    html = render_html(data)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(html, encoding="utf-8")
    print(f"Wrote {OUT_PATH.relative_to(REPO_ROOT)} ({len(html):,} bytes)")
