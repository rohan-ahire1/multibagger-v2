// The bundle written by `mb dashboard export`. Dates are ISO strings; indexes point into `cal`, `symbols` or `weeks`.
export type Trade = [
  symbol: number, entry: number, exit: number, size: number, pnl: number,
  returnPct: number, holdDays: number, status: string, entryPx: number | null, exitPx: number | null,
]
export type Rec = Record<string, number | null | undefined | object>

export interface Run {
  id: string
  label: string
  group: string
  note: string
  tag: string
  strategy: string
  config: string
  config_hash: string
  dataset: string
  final: boolean
  question: string | null
  period: [string, string]
  px_source: 'recorded' | 'dataset'
  equity: (number | null)[]
  positions: (number | null)[]
  trades: Trade[]
  metrics: Rec
  folds: Record<string, Rec>
  baselines: Record<string, Record<string, Rec>>
}

export interface PaperLive {
  as_of: string
  equity: number
  cash: number
  return_pct: number
  positions: { symbol: string; shares: number; entry: string; close: number; value: number; weight_pct: number; gain_pct: number | null }[]
  pending: number
  pending_decided: string | null
  sessions: number
  decisions: number
  last_decision: string | null
  curve: [string, number][]
  fills: { session: string; symbol: string; side: string; shares: number; price: number; cash_flow: number }[]
}

export interface PaperBook {
  name: string
  label: string
  config: string
  strategy: string
  timer: string
  backtest_run: string
  start: string
  capital: number
  first_decision: string | null
  preview: { as_of: string; n: number; picks: [string, number, number, number][]; bench: string[] }
  live: PaperLive | null
}

export interface Bundle {
  generated: string
  config: string
  name: string
  dataset: string
  data_to: string
  cal: string[]
  weeks: number[]
  symbols: string[]
  sectors: string[]
  funds: number[]
  groups: string[]
  runs: Run[]
  price_sets: Record<string, Record<string, [number, number[]][]>>
  tri: (number | null)[]
  locked_from: string
  folds: [string, string, string][]
  adoption_metric: 'calmar' | 'cagr_pct'
  ui: { page_size: number; return_buckets: number[]; range_years: number[]; heat_full_pct: number }
  chart: { weeks_before: number; weeks_after: number }
  paper: { dataset: string; books: PaperBook[] }
}
