"""The VCP pattern check (docs/research/m8_vcp.md): a funnel of where candidate days drop out, and charts of sampled
breakouts drawn up to the breakout day only, so no returns are seen before the pattern is approved."""
from __future__ import annotations

import html
from datetime import date
from pathlib import Path

import numpy as np
import polars as pl

from mb.config.loader import Resolved
from mb.strategy.vcp.pattern import REASONS, STAGE, Found
from mb.strategy.vcp.run import Scan, detect

STAGES = ("Trend template", "Valid base", "Volume dry-up", "Breakout")


def funnel(reasons: pl.DataFrame) -> pl.DataFrame:
    """Per year: candidate days reaching each stage, plus distinct symbols with a breakout."""
    r = reasons.with_columns(pl.col("reason").replace_strict(STAGE, return_dtype=pl.Int64).alias("stage"),
                             pl.col("date").dt.year().alias("year"))
    agg = [pl.len().alias(STAGES[0])] + [(pl.col("stage") >= s).sum().alias(STAGES[s - 1]) for s in (2, 3, 4)]
    agg.append(pl.col("symbol").filter(pl.col("stage") == 4).n_unique().alias("Symbols"))
    by_year = r.group_by("year").agg(agg).sort("year").with_columns(pl.col("year").cast(pl.String))
    total = r.select(agg).with_columns(pl.lit("All").alias("year"))
    return pl.concat([by_year, total.select(by_year.columns)])


def reason_counts(reasons: pl.DataFrame) -> pl.DataFrame:
    counts = dict(reasons.group_by("reason").len().iter_rows())
    return pl.DataFrame({"reason": list(REASONS), "stage": [STAGE[r] for r in REASONS],
                         "days": [counts.get(r, 0) for r in REASONS]})


def sample(sc: Scan, n: int, seed: int) -> list[tuple[str, Found]]:
    hits = [(s, h) for s in sorted(sc.found) for h in sc.found[s]]
    idx = np.random.default_rng(seed).choice(len(hits), size=min(n, len(hits)), replace=False)
    return sorted((hits[i] for i in idx), key=lambda x: (x[0], x[1].day))


def write(cfg: Resolved, root: Path, out: Path, n: int, seed: int) -> Path:
    sc = detect(cfg, root)
    out.mkdir(parents=True, exist_ok=True)
    fun, why = funnel(sc.reasons), reason_counts(sc.reasons)
    picks = sample(sc, n, seed)
    rows = []
    for sym, hits in sc.found.items():
        o = sc.offsets[sym]
        for h in hits:
            rows.append({"symbol": sym, "date": sc.frame["date"][o + h.day], "contractions": len(h.contractions),
                         "depths": [round(c.depth, 4) for c in h.contractions], "pivot": h.pivot, "stop": h.stop,
                         "base_sessions": h.day - h.contractions[0].high_i})
    pl.DataFrame(rows).sort("date", "symbol").write_parquet(out / "breakouts.parquet")
    (out / "funnel.md").write_text(_markdown(cfg, fun, why))
    page = out / "charts.html"
    page.write_text(_html(cfg, sc, fun, why, picks, seed))
    return page


def _markdown(cfg: Resolved, fun: pl.DataFrame, why: pl.DataFrame) -> str:
    cols = fun.columns
    lines = [f"# VCP pattern check: {cfg.strategy.version}", "",
             f"Config `{cfg.strategy_path.name}` (hash {cfg.hash()[:8]}), dataset `{cfg.strategy.dataset}`, "
             f"{cfg.strategy.period.start} to {cfg.strategy.period.end}. Candidate days are stock-days whose previous "
             "close passed the trend template (RS included).", "",
             "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(str(v) for v in r) + " |" for r in fun.iter_rows()]
    lines += ["", "| First failed rule | Stage | Days |", "|---|---|---|"]
    lines += [f"| {r} | {s} | {d} |" for r, s, d in why.iter_rows()]
    return "\n".join(lines) + "\n"


# --- page ------------------------------------------------------------------------------------------------------------

W, PH, VH, GAP, PAD_L, PAD_R, PAD_T = 720.0, 250.0, 70.0, 14.0, 8.0, 56.0, 12.0
PRE_SESSIONS = 40
REASON_TEXT = {
    "breakout": "Breakout", "no_swing_high": "No swing high in the window", "above_base_high":
    "Price already above the base high", "base_too_short": "Base shorter than the minimum", "too_few_contractions":
    "Too few contractions", "too_many_contractions": "Too many contractions", "first_too_deep":
    "First contraction too deep", "not_contracting": "A contraction not shallower than the one before",
    "last_too_deep": "Last contraction too deep", "pivot_too_low": "Pivot too far below the base high",
    "volume_not_lower": "Volume in the last contraction not lower", "no_quiet_day": "No quiet day in the last contraction",
    "no_close_above_pivot": "No close through the pivot", "breakout_volume_low": "Breakout volume too low",
}


def _chart(sc: Scan, sym: str, h: Found, quiet_ratio: float) -> str:
    o = sc.offsets[sym]
    lo_i = max(0, h.contractions[0].high_i - PRE_SESSIONS)
    s = slice(o + lo_i, o + h.day + 1)
    f = sc.frame[s]
    op, hi, lo, cl = (f[c].to_numpy() for c in ("open", "high", "low", "close"))
    vol, vavg, sma = f["volume"].to_numpy(), f["vol_avg"].to_numpy(), f["sma_fast"].to_numpy()
    n = len(hi)
    step = (W - PAD_L - PAD_R) / n
    pmin, pmax = float(np.nanmin(lo)), float(np.nanmax(hi))
    pad = (pmax - pmin) * 0.06
    pmin, pmax = pmin - pad, pmax + pad
    vmax = float(np.nanmax(vol)) or 1.0

    def x(i: int) -> float:
        return PAD_L + (i - lo_i + 0.5) * step

    def y(p: float) -> float:
        return PAD_T + (pmax - p) / (pmax - pmin) * PH

    vy0 = PAD_T + PH + GAP + VH

    def vy(v: float) -> float:
        return vy0 - v / vmax * VH

    last = h.contractions[-1]
    parts = [f'<rect class="band" x="{x(h.day) - step / 2:.1f}" y="{PAD_T}" width="{step:.1f}" height="{vy0 - PAD_T:.1f}"/>']
    # price grid: four levels with labels on the right
    for q in np.linspace(pmin + pad, pmax - pad, 4):
        parts.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(q):.1f}" y2="{y(q):.1f}"/>'
                     f'<text class="ax" x="{W - PAD_R + 6}" y="{y(q) + 3.5:.1f}">{q:,.0f}</text>')
    pts = " ".join(f"{x(lo_i + i):.1f},{y(v):.1f}" for i, v in enumerate(sma) if np.isfinite(v))
    if pts:
        parts.append(f'<polyline class="sma" points="{pts}"/>')
    for i in range(n):
        cls = "up" if cl[i] >= op[i] else "dn"
        xi = x(lo_i + i)
        parts.append(f'<line class="{cls}" x1="{xi:.1f}" x2="{xi:.1f}" y1="{y(hi[i]):.1f}" y2="{y(lo[i]):.1f}"/>'
                     f'<line class="{cls}" x1="{xi:.1f}" x2="{xi + step * 0.45:.1f}" y1="{y(cl[i]):.1f}" y2="{y(cl[i]):.1f}"/>')
    for t, is_high, px in h.swings:
        if t >= lo_i:
            parts.append(f'<circle class="{"sh" if is_high else "sl"}" cx="{x(t):.1f}" cy="{y(px) + (-5 if is_high else 5):.1f}" r="2.2"/>')
    for k, c in enumerate(h.contractions, 1):
        parts.append(f'<line class="cx" x1="{x(c.high_i):.1f}" y1="{y(c.high):.1f}" x2="{x(c.low_i):.1f}" y2="{y(c.low):.1f}"/>')
        ty = min(y(c.low) + 14, PAD_T + PH - 2)
        parts.append(f'<text class="dl" x="{(x(c.high_i) + x(c.low_i)) / 2:.1f}" y="{ty:.1f}">{c.depth * 100:.0f}%</text>')
    parts.append(f'<line class="pivot" x1="{x(last.high_i):.1f}" x2="{W - PAD_R}" y1="{y(h.pivot):.1f}" y2="{y(h.pivot):.1f}"/>'
                 f'<text class="pl" x="{W - PAD_R + 6}" y="{y(h.pivot) + 3.5:.1f}">pivot</text>')
    parts.append(f'<line class="stopl" x1="{x(last.low_i):.1f}" x2="{W - PAD_R}" y1="{y(h.stop):.1f}" y2="{y(h.stop):.1f}"/>')
    # volume
    q_from = last.high_i
    for i in range(n):
        j = lo_i + i
        quiet = q_from <= j < h.day and np.isfinite(vavg[i]) and vol[i] < quiet_ratio * vavg[i]
        cls = "vb" if j == h.day else "vq" if quiet else "vv"
        parts.append(f'<rect class="{cls}" x="{x(j) - step * 0.35:.1f}" y="{vy(vol[i]):.1f}" width="{step * 0.7:.1f}" height="{vy0 - vy(vol[i]):.1f}"/>')
    vpts = " ".join(f"{x(lo_i + i):.1f},{vy(v):.1f}" for i, v in enumerate(vavg) if np.isfinite(v))
    if vpts:
        parts.append(f'<polyline class="vavg" points="{vpts}"/>')
    parts.append(f'<text class="ax" x="{W - PAD_R + 6}" y="{vy0 - VH + 8:.1f}">vol</text>')
    d0, d1 = f["date"][0], f["date"][-1]
    parts.append(f'<text class="ax" x="{PAD_L}" y="{vy0 + 14:.1f}">{d0:%d %b %Y}</text>'
                 f'<text class="ax end" x="{W - PAD_R}" y="{vy0 + 14:.1f}">{d1:%d %b %Y}</text>')
    return (f'<svg viewBox="0 0 {W:.0f} {vy0 + 20:.0f}" role="img" aria-label="{html.escape(sym)} base and breakout">'
            + "".join(parts) + "</svg>")


def _html(cfg: Resolved, sc: Scan, fun: pl.DataFrame, why: pl.DataFrame, picks: list[tuple[str, Found]], seed: int) -> str:
    e = html.escape
    head = "".join(f"<th>{e(c)}</th>" for c in fun.columns)
    body = "".join("<tr" + (' class="tot"' if r[0] == "All" else "") + ">"
                   + "".join(f"<td>{v:,}</td>" if isinstance(v, int) else f"<td>{e(str(v))}</td>" for v in r) + "</tr>"
                   for r in fun.iter_rows())
    total = int(why["days"].sum())
    reasons = "".join(
        f'<tr><td>{e(REASON_TEXT[r])}</td><td>{STAGES[s - 1] if s < 4 else "Passed"}</td><td>{d:,}</td>'
        f'<td><span class="bar" style="--w:{d / total * 100 if total else 0:.1f}%"></span></td></tr>'
        for r, s, d in why.iter_rows())
    quiet = cfg.params.volume.max_quiet_day_to_avg
    cards = []
    for k, (sym, h) in enumerate(picks, 1):
        o = sc.offsets[sym]
        day: date = sc.frame["date"][o + h.day]
        depths = " → ".join(f"{c.depth * 100:.0f}%" for c in h.contractions)
        base = h.day - h.contractions[0].high_i
        cards.append(
            f'<article class="card" id="c{k}"><header><span class="num">{k}</span><h3>{e(sym)}</h3>'
            f'<time datetime="{day}">{day:%d %b %Y}</time></header>'
            f'<dl><div><dt>Contractions</dt><dd>{depths}</dd></div><div><dt>Base</dt><dd>{base} sessions</dd></div>'
            f'<div><dt>Pivot</dt><dd>{h.pivot:,.2f}</dd></div><div><dt>Stop</dt><dd>{h.stop:,.2f} '
            f'({(1 - h.stop / h.pivot) * 100:.1f}% below)</dd></div></dl>{_chart(sc, sym, h, quiet)}</article>')
    n_found = sum(len(v) for v in sc.found.values())
    p = cfg.strategy
    return PAGE.format(
        version=e(p.version), config=e(cfg.strategy_path.name), hash=cfg.hash()[:8], dataset=e(p.dataset),
        start=f"{p.period.start:%d %b %Y}", end=f"{p.period.end:%d %b %Y}", n_found=f"{n_found:,}",
        n_shown=len(picks), seed=seed, head=head, body=body, reasons=reasons, cards="".join(cards),
    )


PAGE = """<title>VCP Pattern Check</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: one review column; summary tables first, then a two-up grid of numbered breakout charts. */
:root {{
  --bg: #f6f7f9; --panel: #ffffff; --ink: #16202c; --muted: #647184; --line: #e2e6ec;
  --accent: #2c62d6; --accent-soft: #c9d8f6; --band: #eef3fd; --stop: #b0485a;
  --sans: "IBM Plex Sans", system-ui, sans-serif; --mono: "IBM Plex Mono", ui-monospace, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #0f141b; --panel: #161d27; --ink: #e3e8ef; --muted: #8b97a8; --line: #253040;
  --accent: #6d9bff; --accent-soft: #2a3f6b; --band: #1a2638; --stop: #e07a8b; color-scheme: dark; }} }}
:root[data-theme="dark"] {{
  --bg: #0f141b; --panel: #161d27; --ink: #e3e8ef; --muted: #8b97a8; --line: #253040;
  --accent: #6d9bff; --accent-soft: #2a3f6b; --band: #1a2638; --stop: #e07a8b; color-scheme: dark; }}
body {{ background: var(--bg); color: var(--ink); font: 14px/1.5 var(--sans); }}
main {{ max-width: 1240px; margin: 0 auto; padding: 32px 16px 64px; display: grid; gap: 28px; }}
h1 {{ font-size: 24px; font-weight: 600; margin: 0; text-wrap: balance; }}
h2 {{ font-size: 15px; font-weight: 600; margin: 0 0 10px; }}
.meta {{ color: var(--muted); font: 12px/1.6 var(--mono); margin-top: 6px; }}
.lede {{ max-width: 68ch; margin: 10px 0 0; }}
.cols {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 460px), 1fr)); gap: 16px; }}
section.box {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 16px; min-width: 0; }}
.scroll {{ overflow-x: auto; }}
table {{ border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }}
th, td {{ text-align: right; padding: 5px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--muted); font-weight: 500; }}
tr.tot td {{ font-weight: 600; border-bottom: 0; }}
.why td:nth-child(2) {{ color: var(--muted); text-align: left; }}
.bar {{ display: inline-block; height: 6px; width: var(--w); min-width: 1px; background: var(--accent); border-radius: 3px; }}
.why td:last-child {{ width: 30%; text-align: left; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 6px 18px; color: var(--muted); font-size: 12px; }}
.legend i {{ display: inline-block; width: 14px; height: 3px; vertical-align: middle; margin-right: 6px; background: var(--accent); }}
.legend i.d {{ background: none; border-top: 2px dashed var(--accent); }}
.legend i.s {{ background: none; border-top: 2px dotted var(--stop); }}
.legend i.m {{ background: var(--muted); }}
.legend i.q {{ height: 9px; width: 9px; background: var(--accent-soft); }}
.grid2 {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 540px), 1fr)); gap: 16px; }}
.card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; padding: 14px 14px 8px; min-width: 0; }}
.card header {{ display: flex; align-items: baseline; gap: 10px; }}
.card h3 {{ margin: 0; font-size: 16px; font-weight: 600; }}
.card time {{ margin-left: auto; color: var(--muted); font: 12px var(--mono); }}
.num {{ font: 500 12px var(--mono); color: var(--accent); min-width: 2ch; }}
dl {{ display: flex; flex-wrap: wrap; gap: 4px 20px; margin: 8px 0 6px; font-size: 12px; }}
dl div {{ display: flex; gap: 6px; }} dt {{ color: var(--muted); }} dd {{ margin: 0; font-family: var(--mono); }}
svg {{ width: 100%; height: auto; display: block; }}
svg text {{ font: 10px var(--mono); fill: var(--muted); }}
svg .end {{ text-anchor: end; }}
svg .grid {{ stroke: var(--line); stroke-width: 1; }}
svg .band {{ fill: var(--band); }}
svg .up {{ stroke: var(--ink); stroke-width: 1.2; }}
svg .dn {{ stroke: var(--muted); stroke-width: 1.2; }}
svg .sma {{ fill: none; stroke: var(--muted); stroke-width: 1; stroke-dasharray: 1 2; }}
svg .sh, svg .sl {{ fill: var(--accent); }}
svg .cx {{ stroke: var(--accent); stroke-width: 1.6; }}
svg .dl {{ fill: var(--accent); text-anchor: middle; font-weight: 500; }}
svg .pivot {{ stroke: var(--accent); stroke-width: 1.2; stroke-dasharray: 5 3; }}
svg .pl {{ fill: var(--accent); }}
svg .stopl {{ stroke: var(--stop); stroke-width: 1.2; stroke-dasharray: 2 3; }}
svg .vv {{ fill: var(--line); }} svg .vq {{ fill: var(--accent-soft); }} svg .vb {{ fill: var(--accent); }}
svg .vavg {{ fill: none; stroke: var(--muted); stroke-width: 1; }}
</style>
<main>
  <header>
    <h1>VCP pattern check · {version}</h1>
    <div class="meta">{config} · hash {hash} · {dataset} · {start} to {end}</div>
    <p class="lede">The detector found {n_found} breakouts. Below are {n_shown} picked at random (seed {seed}). Each chart
    stops on the breakout day, so no outcomes are shown. For each one, judge by eye: is this a real VCP? Reply with
    the numbers that are not.</p>
  </header>
  <div class="cols">
    <section class="box"><h2>Where candidate days drop out</h2><div class="scroll"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></section>
    <section class="box"><h2>First rule each candidate day failed</h2><div class="scroll"><table class="why"><thead><tr><th>Rule</th><th>Stage</th><th>Days</th><th></th></tr></thead><tbody>{reasons}</tbody></table></div></section>
  </div>
  <section>
    <h2>Sampled breakouts</h2>
    <div class="legend"><span><i></i>contraction, high to low, with depth</span><span><i class="d"></i>pivot</span>
    <span><i class="s"></i>stop (last contraction low)</span><span><i class="m"></i>50-day average</span>
    <span><i class="q"></i>quiet volume day (below the dry-up threshold)</span><span>shaded column: breakout day</span></div>
  </section>
  <div class="grid2">{cards}</div>
</main>
"""
