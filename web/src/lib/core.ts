// Calculations over the bundle, ported from the approved mockup (mbcore.js). Pure functions; no UI.
import { fdate, fdateShort, fmtPx, inr, inrSigned, MONTHS, pct, pctPlain, tone, type Tone } from './format'
import type { Bundle, Rec, Run, Trade } from './types'

export type Series = { id: string; equity: (number | null)[]; positions: (number | null)[]; trades: Trade[]; period?: [string, string] }
export type Range = [number, number]
export interface Metrics {
  start: string; end: string; years: number; startEq: number; endEq: number
  total: number; cagr: number; mdd: number; calmar: number | null; vol: number; sharpe: number | null; sortino: number | null
  bestMonth: number | null; worstMonth: number | null; posMonths: number | null; months: number
  ddDays: number; ddPeak: string; ddTrough: string; currentDD: number; avgPositions: number | null
  trades: number; winRate: number | null; avgWin: number | null; avgLoss: number | null; profitFactor: number | null
  avgHold: number | null; expectancy: number | null; payoff: number | null; openTrades: number
  bestTrade: number | null; worstTrade: number | null; bestTradeSym: string; worstTradeSym: string; netPnl: number
}
export interface Preset { id: string; label: string; from?: string; to?: string; years?: number }
export interface Line { d: string; color: string; width: number; dash: string; label: string; end: number | null; endText: string; endY: number }
export interface EquityChart {
  lines: Line[]; grid: { y: number; label: string }[]; ticks: { x: number; label: string }[]
  dd: string; ddLabel: string; ddFloorLabel: string; i0: number; i1: number
}
export interface SeriesIn { label: string; values: (number | null)[]; color: string; width?: number; dash?: string }
export interface TradeRow {
  key: string; i: number; sym: string; sector: string; entry: string; exit: string; entryIso: string; exitIso: string
  entryPx: string; exitPx: string; size: string; pnl: string; ret: string; retV: number; hold: string; tone: Tone; status: string; statusKey: string
}
export interface TradeQuery { q?: string; side?: 'all' | 'win' | 'loss'; sort?: 'entry' | 'ret' | 'pnl' | 'hold' | 'sym'; dir?: 'asc' | 'desc'; page?: number; size?: number }

const STATUS: Record<string, string> = {
  rebalanced_out: 'Rebalanced out', open: 'Open at end', stopped: 'Stop', intraday_stop: 'Intraday stop', max_hold: 'Max hold',
  stagnation_next_open: 'Stagnation', trail_ema_hybrid_next_open: 'Trailing exit',
}
const DAY = 864e5

export function recNum(r: Rec, k: string): number | null {
  const v = r[k]
  return typeof v === 'number' && isFinite(v) ? v : null
}

export function niceStep(x: number): number {
  const p = Math.pow(10, Math.floor(Math.log10(x))), m = x / p
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p
}

export function createCore(D: Bundle) {
  const cache = new Map<string, unknown>()
  const cal = D.cal
  const funds = new Set(D.funds)
  const fundNames = new Set(D.funds.map((i) => D.symbols[i]))
  const bench: Series & { label: string } = { id: 'tri', label: 'Nifty 500 TRI', equity: D.tri, positions: new Array(cal.length).fill(null), trades: [] }

  // ---- dates ----
  function idxAtOrAfter(iso: string): number {
    let lo = 0, hi = cal.length - 1
    if (iso <= cal[0]) return 0
    if (iso > cal[hi]) return hi
    while (lo < hi) { const m = (lo + hi) >> 1; if (cal[m] < iso) lo = m + 1; else hi = m }
    return lo
  }
  function idxAtOrBefore(iso: string): number {
    const i = idxAtOrAfter(iso)
    return cal[i] > iso && i > 0 ? i - 1 : i
  }
  const dayBefore = (iso: string) => new Date(Date.parse(iso) - DAY).toISOString().slice(0, 10)

  // ---- runs ----
  const runById = new Map(D.runs.map((r) => [r.id, r]))
  const run = (id: string): Run => runById.get(id) ?? D.runs[0]
  function span(r: Series): Range {
    const k = 'span:' + r.id
    const hit = cache.get(k) as Range | undefined
    if (hit) return hit
    const e = r.equity
    let a = 0, b = e.length - 1
    while (a < e.length && e[a] === null) a++
    while (b > 0 && e[b] === null) b--
    // A run may record equity past its period end (settle days); its metrics stop at the period end, so the span does too.
    if (r.period) { a = Math.max(a, idxAtOrAfter(r.period[0])); b = Math.min(b, idxAtOrBefore(r.period[1])) }
    const out: Range = [a, b]
    cache.set(k, out)
    return out
  }

  // ---- date ranges: presets come from the bundle (folds, locked start) and the config's trailing years ----
  const presets: Preset[] = (() => {
    const out: Preset[] = [{ id: 'all', label: 'All' }]
    const dev = dayBefore(D.locked_from)
    out.push({ id: 'dev', label: `${cal[0].slice(0, 4)}–${dev.slice(2, 4)}`, to: dev })
    for (const [name, start, end] of D.folds) out.push({ id: name, label: `${start.slice(0, 4)}–${end.slice(2, 4)}`, from: start, to: end })
    out.push({ id: 'locked', label: `${D.locked_from.slice(0, 4)} →`, from: D.locked_from })
    for (const y of D.ui.range_years) out.push({ id: `${y}y`, label: `${y}Y`, years: y })
    return out
  })()
  function presetRange(id: string, r: Series): Range {
    const s = span(r)
    const p = presets.find((x) => x.id === id)
    if (!p || id === 'all') return s
    const clamp = (a: number, b: number): Range => [Math.max(s[0], a), Math.min(s[1], b)]
    if (p.years) {
      const end = cal[s[1]]
      return clamp(idxAtOrAfter(+end.slice(0, 4) - p.years + end.slice(4)), s[1])
    }
    return clamp(p.from ? idxAtOrAfter(p.from) : 0, p.to ? idxAtOrBefore(p.to) : s[1])
  }
  function customRange(fromIso: string, toIso: string, r: Series): Range {
    const s = span(r)
    const a = Math.max(s[0], idxAtOrAfter(fromIso)), b = Math.min(s[1], idxAtOrBefore(toIso))
    return b > a ? [a, b] : s
  }

  // ---- metrics ----
  function monthlyReturns(r: Series, i0: number, i1: number) {
    const e = r.equity
    const ends: [string, number][] = []
    const list: number[] = []
    const byYear: Record<string, (number | null)[]> = {}
    let lastM: string | null = null, prevEq: number | null = null
    for (let i = i0; i <= i1; i++) {
      const v = e[i]
      if (v === null) continue
      if (prevEq === null) prevEq = v
      const m = cal[i].slice(0, 7)
      if (m !== lastM) { ends.push([m, i]); lastM = m } else ends[ends.length - 1][1] = i
    }
    for (const [ym, idx] of ends) {
      const v = e[idx] as number
      const ret = v / (prevEq as number) - 1
      prevEq = v
      list.push(ret)
      const y = ym.slice(0, 4), mo = +ym.slice(5, 7) - 1
      ;(byYear[y] = byYear[y] || new Array(12).fill(null))[mo] = ret * 100
    }
    return { list, byYear }
  }
  function tradeStats(r: Series, i0: number, i1: number) {
    let w = 0, l = 0, gw = 0, gl = 0, rw = 0, rl = 0, hold = 0, n = 0, open = 0, rsum = 0
    let best: number | null = null, worst: number | null = null
    const tr = r.trades
    for (let i = 0; i < tr.length; i++) {
      const t = tr[i]
      if (t[1] < i0 || t[1] > i1) continue
      n++; hold += t[6] || 0; rsum += t[5] || 0
      if (t[7] === 'open') open++
      if (t[4] > 0) { w++; gw += t[4]; rw += t[5] } else { l++; gl += t[4]; rl += t[5] }
      if (best === null || t[5] > tr[best][5]) best = i
      if (worst === null || t[5] < tr[worst][5]) worst = i
    }
    return {
      trades: n, winRate: n ? (w / n) * 100 : null, avgWin: w ? rw / w : null, avgLoss: l ? rl / l : null,
      profitFactor: gl < 0 ? gw / -gl : null, avgHold: n ? hold / n : null, expectancy: n ? rsum / n : null,
      payoff: w && l && rl ? rw / w / Math.abs(rl / l) : null, openTrades: open,
      bestTrade: best === null ? null : tr[best][5], worstTrade: worst === null ? null : tr[worst][5],
      bestTradeSym: best === null ? '' : D.symbols[tr[best][0]], worstTradeSym: worst === null ? '' : D.symbols[tr[worst][0]],
      netPnl: gw + gl,
    }
  }
  function metrics(r: Series, i0: number, i1: number): Metrics | null {
    const k = `m:${r.id}:${i0}:${i1}`
    if (cache.has(k)) return cache.get(k) as Metrics | null
    const e = r.equity
    const pts: number[] = []
    for (let i = i0; i <= i1; i++) if (e[i] !== null) pts.push(i)
    if (pts.length < 2) { cache.set(k, null); return null }
    const first = e[pts[0]] as number, last = e[pts[pts.length - 1]] as number
    const years = (Date.parse(cal[pts[pts.length - 1]]) - Date.parse(cal[pts[0]])) / (365.25 * DAY)
    const total = last / first - 1
    const cagr = years > 0 ? Math.pow(last / first, 1 / years) - 1 : 0
    let peak = first, mdd = 0, peakAt = pts[0], ddStart = pts[0], longest = 0, sum = 0, sum2 = 0, dn2 = 0, n = 0
    let troughAt = pts[0], mddPeakAt = pts[0]
    for (let j = 1; j < pts.length; j++) {
      const v = e[pts[j]] as number, prev = e[pts[j - 1]] as number, ret = v / prev - 1
      sum += ret; sum2 += ret * ret; if (ret < 0) dn2 += ret * ret; n++
      if (v >= peak) {
        const dur = (Date.parse(cal[pts[j]]) - Date.parse(cal[ddStart])) / DAY
        if (dur > longest) longest = dur
        peak = v; peakAt = pts[j]; ddStart = pts[j]
      } else {
        const dd = v / peak - 1
        if (dd < mdd) { mdd = dd; troughAt = pts[j]; mddPeakAt = peakAt }
      }
    }
    const openDur = (Date.parse(cal[pts[pts.length - 1]]) - Date.parse(cal[ddStart])) / DAY
    if (openDur > longest) longest = openDur
    const mean = sum / n, sd = Math.sqrt(Math.max(0, sum2 / n - mean * mean)), dsd = Math.sqrt(dn2 / n)
    const mv = monthlyReturns(r, i0, i1).list
    let pos = 0, best = -Infinity, worst = Infinity
    for (const q of mv) { if (q > 0) pos++; if (q > best) best = q; if (q < worst) worst = q }
    let psum = 0, pc = 0
    for (let z = i0; z <= i1; z++) { const p = r.positions[z]; if (p !== null && p !== undefined) { psum += p; pc++ } }
    const out: Metrics = {
      start: cal[pts[0]], end: cal[pts[pts.length - 1]], years, startEq: first, endEq: last,
      total: total * 100, cagr: cagr * 100, mdd: mdd * 100, calmar: mdd < 0 ? cagr / -mdd : null,
      vol: sd * Math.sqrt(252) * 100, sharpe: sd > 0 ? (mean * 252) / (sd * Math.sqrt(252)) : null,
      sortino: dsd > 0 ? (mean * 252) / (dsd * Math.sqrt(252)) : null,
      bestMonth: isFinite(best) ? best * 100 : null, worstMonth: isFinite(worst) ? worst * 100 : null,
      posMonths: mv.length ? (pos / mv.length) * 100 : null, months: mv.length,
      ddDays: Math.round(longest), ddPeak: cal[mddPeakAt], ddTrough: cal[troughAt],
      currentDD: (last / peak - 1) * 100, avgPositions: pc ? psum / pc : null,
      ...tradeStats(r, i0, i1),
    }
    cache.set(k, out)
    return out
  }

  function heatmap(r: Series, i0: number, i1: number) {
    const by = monthlyReturns(r, i0, i1).byYear
    return Object.keys(by).sort().map((year) => {
      let comp = 1
      const cells = by[year].map((v) => {
        if (v !== null) comp *= 1 + v / 100
        return {
          v, text: v === null ? '' : (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(1),
          tone: (v === null ? 'none' : tone(v)) as Tone | 'none', strength: v === null ? 0 : Math.min(1, Math.abs(v) / D.ui.heat_full_pct),
        }
      })
      const yr = (comp - 1) * 100
      return { year, cells, total: pct(yr), totalV: yr, tone: tone(yr) }
    })
  }
  const yearly = (r: Series, i0: number, i1: number) => heatmap(r, i0, i1).map((h) => ({ year: h.year, v: h.totalV }))

  // ---- charts (widths and heights are the measured pixel size of the drawing area) ----
  function yearTicks(i0: number, i1: number, w: number, maxTicks: number) {
    const y0 = +cal[i0].slice(0, 4), y1 = +cal[i1].slice(0, 4), sp = Math.max(1, i1 - i0)
    const out: { x: number; label: string }[] = []
    const step = Math.max(1, Math.ceil((y1 - y0 + 1) / maxTicks))
    for (let y = y0 + (cal[i0].slice(5) === '01-01' ? 0 : 1); y <= y1; y += step) {
      const i = idxAtOrAfter(y + '-01-01')
      if (i <= i0 || i >= i1) continue
      out.push({ x: ((i - i0) / sp) * w, label: String(y) })
    }
    if (out.length < 2 && y1 - y0 < 2) {
      out.length = 0
      for (let q = 0; q < 4; q++) { const ii = i0 + Math.round((sp * (q + 0.5)) / 4); out.push({ x: ((ii - i0) / sp) * w, label: fdateShort(cal[ii]) }) }
    }
    return out
  }
  // Equity lines rebased to 100 at the window start, drawn on a log scale, plus the drawdown path of the first line.
  function equityChart(series: SeriesIn[], i0: number, i1: number, w: number, h: number, ddH: number, useLog: boolean): EquityChart {
    const sp = Math.max(1, i1 - i0)
    const raw: { pts: [number, number][]; s: SeriesIn }[] = []
    let lo = Infinity, hi = -Infinity
    for (const s of series) {
      let base: number | null = null
      const pts: [number, number][] = []
      for (let i = i0; i <= i1; i++) {
        const v = s.values[i]
        if (v === null || v === undefined) continue
        if (base === null) base = v
        const y = (v / base) * 100
        pts.push([i, y])
        if (y < lo) lo = y
        if (y > hi) hi = y
      }
      raw.push({ pts, s })
    }
    if (!isFinite(lo)) { lo = 90; hi = 110 }
    const f = useLog ? Math.log : (x: number) => x
    const flo = f(lo * 0.97), fhi = f(hi * 1.03)
    const Y = (y: number) => h - ((f(y) - flo) / (fhi - flo)) * h
    const X = (i: number) => ((i - i0) / sp) * w
    const lines: Line[] = raw.map(({ pts: p, s }) => {
      let d = ''
      const step = Math.max(1, Math.floor(p.length / 1400))
      for (let k = 0; k < p.length; k += step) d += (k ? 'L' : 'M') + X(p[k][0]).toFixed(1) + ' ' + Y(p[k][1]).toFixed(1)
      const lastPt = p.length ? p[p.length - 1] : null
      if (lastPt) d += 'L' + X(lastPt[0]).toFixed(1) + ' ' + Y(lastPt[1]).toFixed(1)
      return {
        d, color: s.color, width: s.width ?? 1.5, dash: s.dash ?? '', label: s.label,
        end: lastPt ? lastPt[1] - 100 : null, endText: lastPt ? pct(lastPt[1] - 100, 0) : '', endY: lastPt ? Y(lastPt[1]) : 0,
      }
    })
    const grid: { y: number; label: string }[] = []
    if (useLog) {
      for (let gv = 25; gv < hi * 1.03; gv *= 2) {
        if (gv > lo * 0.97) grid.push({ y: Y(gv), label: (gv / 100).toFixed(gv < 100 ? 2 : 1).replace(/\.0+$/, '').replace(/(\.\d)0$/, '$1') + '×' })
      }
    } else {
      const g = Math.pow(10, Math.floor(Math.log10(hi - lo)))
      for (let gv = Math.ceil(lo / g) * g; gv < hi; gv += g) grid.push({ y: Y(gv), label: (gv / 100).toFixed(1) + '×' })
    }
    const first = raw[0] ? raw[0].pts : []
    let peak = -Infinity, ddMin = 0
    const ddPts: [number, number][] = []
    for (const [i, v] of first) {
      if (v > peak) peak = v
      const x = v / peak - 1
      ddPts.push([i, x])
      if (x < ddMin) ddMin = x
    }
    const ds = Math.max(1, Math.floor(ddPts.length / 1400)), floor = Math.min(-0.05, ddMin * 1.08)
    const DY = (v: number) => (v / floor) * ddH
    let dd = ''
    if (ddPts.length) {
      dd = 'M' + X(ddPts[0][0]).toFixed(1) + ' 0'
      for (let z = 0; z < ddPts.length; z += ds) dd += 'L' + X(ddPts[z][0]).toFixed(1) + ' ' + DY(ddPts[z][1]).toFixed(1)
      const e = ddPts[ddPts.length - 1]
      dd += 'L' + X(e[0]).toFixed(1) + ' ' + DY(e[1]).toFixed(1) + 'L' + X(e[0]).toFixed(1) + ' 0Z'
    }
    return { lines, grid, ticks: yearTicks(i0, i1, w, Math.max(3, Math.floor(w / 90))), dd, ddLabel: pct(ddMin * 100, 0), ddFloorLabel: pctPlain(floor * 100, 0), i0, i1 }
  }
  function hover(chart: EquityChart, series: SeriesIn[], px: number, w: number) {
    const sp = Math.max(1, chart.i1 - chart.i0)
    const i = chart.i0 + Math.round((px / w) * sp)
    const rows = series.map((s) => {
      let base: number | null = null, at: number | null = null
      for (let k = chart.i0; k <= chart.i1; k++) {
        const v = s.values[k]
        if (v === null || v === undefined) continue
        if (base === null) base = v
        if (k <= i) at = v
      }
      return { label: s.label, color: s.color, text: at === null || base === null ? '—' : pct((at / base - 1) * 100, 1) }
    })
    return { x: px, date: fdate(cal[Math.min(i, cal.length - 1)]), rows }
  }
  function band(i0: number, i1: number, a: number, b: number, w: number) {
    const sp = Math.max(1, i1 - i0)
    const x0 = Math.max(0, ((a - i0) / sp) * w), x1 = Math.min(w, ((b - i0) / sp) * w)
    return x1 > x0 ? { show: true, x: x0, w: Math.max(2, x1 - x0) } : { show: false, x: 0, w: 0 }
  }
  function yearlyBars(r: Series, i0: number, i1: number, w: number, h: number) {
    const ys = yearly(r, i0, i1)
    let mx = 1
    for (const y of ys) mx = Math.max(mx, Math.abs(y.v))
    const bw = ys.length ? w / ys.length : w
    return ys.map((y, k) => {
      const hh = (Math.abs(y.v) / mx) * (h / 2)
      return { year: '’' + y.year.slice(2), text: pct(y.v, 0), tone: tone(y.v), x: k * bw, w: Math.max(4, bw - 6), top: y.v >= 0 ? h / 2 - hh : h / 2, h: Math.max(1, hh) }
    })
  }
  function histogram(r: Series, i0: number, i1: number, w: number, h: number) {
    const edges = D.ui.return_buckets
    const counts: number[] = new Array(edges.length + 1).fill(0)
    for (const t of r.trades) {
      if (t[1] < i0 || t[1] > i1) continue
      let k = 0
      while (k < edges.length && t[5] >= edges[k]) k++
      counts[k]++
    }
    const mx = Math.max(...counts, 1), bw = w / counts.length
    const zero = edges.findIndex((e) => e >= 0)
    const minus = (v: number) => (v < 0 ? '−' + Math.abs(v) : String(v))
    return counts.map((n, k) => {
      const label = k === 0 ? '<' + minus(edges[0]) : k === counts.length - 1 ? '>' + minus(edges[edges.length - 1]) : minus(edges[k - 1])
      const hh = (n / mx) * h
      return { x: k * bw, w: Math.max(1, bw - 4), h: Math.max(n ? 2 : 0, hh), top: h - hh, n, label, tone: (k <= (zero < 0 ? edges.length : zero) ? 'loss' : 'gain') as Tone }
    })
  }

  // ---- trades ----
  const statusLabel = (s: string) => STATUS[s] ?? s
  function tradeRow(r: Series, i: number): TradeRow {
    const t = r.trades[i]
    return {
      key: r.id + ':' + i, i, sym: D.symbols[t[0]], sector: D.sectors[t[0]] || '—',
      entry: fdate(cal[t[1]]), exit: t[2] >= 0 ? fdate(cal[t[2]]) : '—', entryIso: cal[t[1]], exitIso: t[2] >= 0 ? cal[t[2]] : '',
      entryPx: t[8] ? '₹' + t[8].toLocaleString('en-IN') : '—', exitPx: t[9] ? '₹' + t[9].toLocaleString('en-IN') : '—',
      size: t[3] ? inr(t[3]) : '—', pnl: inrSigned(t[4]), ret: pct(t[5], 1), retV: t[5], hold: t[6] + 'd', tone: tone(t[4]),
      status: statusLabel(t[7]), statusKey: t[7],
    }
  }
  function trades(r: Series, i0: number, i1: number, opts: TradeQuery) {
    const tr = r.trades, sy = D.symbols, q = (opts.q || '').toUpperCase()
    const rows: number[] = []
    for (let i = 0; i < tr.length; i++) {
      const t = tr[i]
      if (t[1] < i0 || t[1] > i1) continue
      if (opts.side === 'win' && !(t[4] > 0)) continue
      if (opts.side === 'loss' && t[4] > 0) continue
      if (q && !sy[t[0]].includes(q)) continue
      rows.push(i)
    }
    const dir = opts.dir === 'asc' ? 1 : -1
    const get: Record<string, (i: number) => number | string> = {
      entry: (i) => tr[i][1], ret: (i) => tr[i][5], pnl: (i) => tr[i][4], hold: (i) => tr[i][6], sym: (i) => sy[tr[i][0]],
    }
    const g = get[opts.sort || 'entry']
    rows.sort((a, b) => { const x = g(a), y = g(b); return (x < y ? -1 : x > y ? 1 : 0) * dir || a - b })
    const total = rows.length, size = opts.size || 15, pages = Math.max(1, Math.ceil(total / size))
    const page = Math.min(opts.page || 0, pages - 1)
    return { total, rows: rows.slice(page * size, page * size + size).map((i) => tradeRow(r, i)), pages, page, order: rows, size }
  }

  const weekOf = (ci: number) => {
    const wk = D.weeks
    let lo = 0, hi = wk.length - 1
    while (lo < hi) { const m = (lo + hi) >> 1; if (wk[m] < ci) lo = m + 1; else hi = m }
    return lo
  }
  function tickMonths(i0: number, i1: number, w: number) {
    const out: { x: number; label: string }[] = []
    const sp = Math.max(1, i1 - i0), months = (Date.parse(cal[i1]) - Date.parse(cal[i0])) / (30.4 * DAY)
    const step = months > 30 ? 12 : months > 14 ? 6 : 3
    let y = +cal[i0].slice(0, 4), m = +cal[i0].slice(5, 7)
    for (let k = 0; k < 40; k++) {
      m += 1
      if (m > 12) { m = 1; y++ }
      if ((m - 1) % step !== 0) continue
      const ii = idxAtOrAfter(`${y}-${m < 10 ? '0' : ''}${m}-01`)
      if (ii >= i1) break
      out.push({ x: ((ii - i0) / sp) * w, label: MONTHS[m - 1] + ' ’' + String(y).slice(2) })
    }
    return out
  }
  // Price chart of one trade's symbol: weekly adjusted close from the run's own dataset, the entry and exit at their fill
  // prices, and the run's other trades in the same name as clickable spans.
  function tradeChart(r: Run, i: number, w: number, h: number) {
    const t = r.trades[i], wk = D.weeks
    const segs = D.price_sets[r.dataset]?.[String(t[0])] ?? []
    const ew = weekOf(t[1]), xw = weekOf(t[2] >= 0 ? t[2] : cal.length - 1)
    const seg = segs.find((s) => s[0] <= ew && s[0] + s[1].length > ew)
    if (!seg) return null
    const a = Math.max(seg[0], ew - D.chart.weeks_before), b = Math.min(seg[0] + seg[1].length - 1, xw + D.chart.weeks_after)
    const pts: [number, number][] = []
    for (let k = a; k <= b; k++) { const v = seg[1][k - seg[0]]; if (v !== null && v !== undefined) pts.push([wk[k], v]) }
    if (pts.length < 2) return null
    const i0 = pts[0][0], i1 = pts[pts.length - 1][0]
    let lo = Infinity, hi = -Infinity
    for (const [, v] of pts) { lo = Math.min(lo, v); hi = Math.max(hi, v) }
    if (t[8]) { lo = Math.min(lo, t[8]); hi = Math.max(hi, t[8]) }
    if (t[9]) { lo = Math.min(lo, t[9]); hi = Math.max(hi, t[9]) }
    const pad = (hi - lo) * 0.12 || hi * 0.05
    lo -= pad; hi += pad
    const X = (ix: number) => ((ix - i0) / Math.max(1, i1 - i0)) * w, Y = (v: number) => h - ((v - lo) / (hi - lo)) * h
    let line = ''
    pts.forEach((p, q) => { line += (q ? 'L' : 'M') + X(p[0]).toFixed(1) + ' ' + Y(p[1]).toFixed(1) })
    const ex = t[2] >= 0 ? t[2] : cal.length - 1, x0 = X(t[1]), x1 = X(Math.min(ex, i1)), up = t[4] > 0
    const yEntry = Y(t[8] || pts[0][1]), yExit = Y(t[9] || pts[pts.length - 1][1])
    const others: { x: number; w: number; tone: Tone; text: string; idx: number }[] = []
    r.trades.forEach((u, o) => {
      if (o === i || u[0] !== t[0]) return
      const ue = u[2] >= 0 ? u[2] : cal.length - 1
      if (ue < i0 || u[1] > i1) return
      const ox0 = Math.max(0, X(u[1])), ox1 = Math.min(w, X(ue))
      others.push({ x: ox0, w: Math.max(2, ox1 - ox0), tone: tone(u[4]), text: pct(u[5], 0), idx: o })
    })
    const grid: { y: number; label: string }[] = []
    const stepV = niceStep((hi - lo) / 4)
    for (let gv = Math.ceil(lo / stepV) * stepV; gv < hi; gv += stepV) grid.push({ y: Y(gv), label: '₹' + fmtPx(gv) })
    const labelW = 74, lx = Math.min(w - labelW, Math.max(0, x1 - labelW / 2))
    return {
      d: line, ticks: tickMonths(i0, i1, w), grid, hold: { x: x0, w: Math.max(2, x1 - x0) }, up, tone: (up ? 'gain' : 'loss') as Tone,
      entry: { x: x0, y: yEntry, text: '₹' + fmtPx(t[8]) }, exit: { x: x1, y: yExit, text: '₹' + fmtPx(t[9]) },
      label: { x: lx, y: Math.max(0, Math.min(h - 26, (up ? Math.min(yEntry, yExit) : Math.max(yEntry, yExit)) + (up ? -34 : 10))), text: pct(t[5], 1) },
      entryLine: { x: x0, w: Math.max(2, x1 - x0), y: yEntry }, others, row: tradeRow(r, i),
    }
  }

  const isFund = (sym: string) => fundNames.has(sym)
  const isFundIdx = (i: number) => funds.has(i)

  return {
    D, run, span, presets, presetRange, customRange, idxAtOrAfter, idxAtOrBefore, bench, metrics, heatmap, yearlyBars, histogram,
    equityChart, hover, band, trades, tradeRow, tradeChart, isFund, isFundIdx, statusLabel,
  }
}
export type Core = ReturnType<typeof createCore>
