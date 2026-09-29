// The numbers each view shows, as label / text / tone rows. Nothing here draws.
import { fdateShort, inr, num, pct, pctPlain, tone, type Tone } from './format'
import { recNum, type Core, type Metrics } from './core'
import type { Run } from './types'

export interface Item { label: string; value: string; tone: Tone; sub?: string }
const G = (label: string, value: string, t: Tone = 'flat', sub?: string): Item => ({ label, value, tone: t, sub })

// Money shown in "becomes" lines starts from the run's own recorded starting equity, not a typed-in amount.
export function startCapital(run: Run): number {
  return recNum(run.metrics, 'start_equity') ?? 0
}

export function summary(core: Core, run: Run, i0: number, i1: number) {
  const m = core.metrics(run, i0, i1), bm = core.metrics(core.bench, i0, i1)
  if (!m) return null
  const start = startCapital(run)
  const grow = m.startEq ? (start * m.endEq) / m.startEq : null
  const startText = inr(start)
  const kpis: Item[] = [
    G('CAGR', pct(m.cagr, 2), tone(m.cagr), 'Nifty 500 TRI ' + pct(bm?.cagr, 1)),
    G('Total return', pct(m.total, 0), tone(m.total), `${startText} → ${inr(grow)}`),
    G('Max drawdown', pctPlain(m.mdd, 1), 'loss', 'TRI ' + pctPlain(bm?.mdd, 1)),
    G('Calmar', num(m.calmar, 2), 'flat', 'TRI ' + num(bm?.calmar, 2)),
    G('Sharpe', num(m.sharpe, 2), 'flat', 'Sortino ' + num(m.sortino, 2)),
    G('Win rate', pctPlain(m.winRate, 1), 'flat', m.trades.toLocaleString('en-IN') + ' trades'),
  ]
  const rm = run.metrics
  const x = (k: string, f: (v: number) => string) => { const v = recNum(rm, k); return v === null ? '—' : f(v) }
  const groups: { title: string; items: Item[] }[] = [
    { title: 'Returns', items: [
      G('CAGR', pct(m.cagr, 2), tone(m.cagr)), G('Total return', pct(m.total, 1), tone(m.total)), G(`${startText} becomes`, inr(grow)),
      G('Excess CAGR vs TRI', bm ? pct(m.cagr - bm.cagr, 2) : '—', bm ? tone(m.cagr - bm.cagr) : 'flat'),
      G('Best month', pct(m.bestMonth, 1), 'gain'), G('Worst month', pct(m.worstMonth, 1), 'loss'),
      G('Positive months', pctPlain(m.posMonths, 0) + ' of ' + m.months) ] },
    { title: 'Risk', items: [
      G('Max drawdown', pctPlain(m.mdd, 2), 'loss'), G('Drawdown peak → trough', fdateShort(m.ddPeak) + ' → ' + fdateShort(m.ddTrough)),
      G('Longest underwater', m.ddDays ? m.ddDays + ' days' : '—'), G('Drawdown now', pctPlain(m.currentDD, 1), m.currentDD < -0.05 ? 'loss' : 'flat'),
      G('Volatility (ann.)', pctPlain(m.vol, 1)), G('Sharpe (0% rf)', num(m.sharpe, 2)), G('Sortino', num(m.sortino, 2)), G('Calmar', num(m.calmar, 2)) ] },
    { title: 'Trades', items: [
      G('Trades opened', m.trades.toLocaleString('en-IN')), G('Win rate', pctPlain(m.winRate, 1)), G('Profit factor', num(m.profitFactor, 2)),
      G('Average win', pct(m.avgWin, 1), 'gain'), G('Average loss', pct(m.avgLoss, 1), 'loss'), G('Payoff ratio', num(m.payoff, 2)),
      G('Expectancy / trade', pct(m.expectancy, 2), tone(m.expectancy)), G('Average hold', m.avgHold ? Math.round(m.avgHold) + ' days' : '—'),
      G('Best trade', pct(m.bestTrade, 0) + '  ' + m.bestTradeSym, 'gain'), G('Worst trade', pct(m.worstTrade, 0) + '  ' + m.worstTradeSym, 'loss') ] },
    { title: 'Exposure · whole run', items: [
      G('Average positions', num(m.avgPositions, 1)), G('Average invested', x('avg_invested_frac', (v) => pctPlain(v * 100, 1))),
      G('Turnover / year', x('annual_turnover_x', (v) => num(v, 1) + '×')), G('Rebalances', x('rebalances', (v) => (v ? String(v) : '—'))),
      G('Top 5% of trades, share of P&L', x('top5pct_trades_share_of_pnl', (v) => pctPlain(v * 100, 0))) ] },
  ]
  const pick = (label: string) => groups.flatMap((g) => g.items).find((i) => i.label === label) ?? G(label, '—')
  const extras = ['Volatility (ann.)', 'Sortino', 'Profit factor', 'Average hold', 'Positive months', 'Longest underwater']
    .map((k) => ({ ...pick(k), label: k === 'Volatility (ann.)' ? 'Volatility' : k }))
  return { m, bm, kpis, groups, extras }
}

// Compare table rows: label, metric key, formatter, and which way is better (1 higher, -1 lower, 0 none).
export const COMPARE_ROWS: [string, keyof Metrics, (v: number | null) => string, 1 | -1 | 0][] = [
  ['CAGR', 'cagr', (v) => pct(v, 2), 1], ['Total return', 'total', (v) => pct(v, 0), 1], ['Max drawdown', 'mdd', (v) => pctPlain(v, 1), 1],
  ['Calmar', 'calmar', (v) => num(v, 2), 1], ['Sharpe', 'sharpe', (v) => num(v, 2), 1], ['Volatility', 'vol', (v) => pctPlain(v, 1), -1],
  ['Worst month', 'worstMonth', (v) => pct(v, 1), 1], ['Trades', 'trades', (v) => (v === null ? '—' : v.toLocaleString('en-IN')), 0],
  ['Win rate', 'winRate', (v) => pctPlain(v, 1), 1], ['Profit factor', 'profitFactor', (v) => num(v, 2), 1],
  ['Average hold', 'avgHold', (v) => (v ? Math.round(v) + 'd' : '—'), 0],
]
