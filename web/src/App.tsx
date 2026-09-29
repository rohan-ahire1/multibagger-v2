import { useCallback, useEffect, useMemo, useState } from 'react'
import { DateRange, PageHead } from './components/PageHead'
import { Picker } from './components/Picker'
import { TopBar, VIEWS, type View } from './components/TopBar'
import { createCore, type Range } from './lib/core'
import type { Ctx } from './lib/ctx'
import { fdate } from './lib/format'
import { MAX_COMPARE } from './lib/series'
import type { Bundle } from './lib/types'
import { Compare } from './views/Compare'
import { Metrics } from './views/Metrics'
import { Monthly } from './views/Monthly'
import { Overview } from './views/Overview'
import { Paper, PaperHeadToggle } from './views/Paper'
import { Trades } from './views/Trades'

const THEME_KEY = 'mb-dashboard-theme'
type Theme = 'light' | 'dark'

function useBundle() {
  const [state, set] = useState<{ D: Bundle | null; error: string | null }>({ D: null, error: null })
  useEffect(() => {
    fetch(import.meta.env.BASE_URL + 'bundle.json')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`bundle.json: HTTP ${r.status}`))))
      .then((D: Bundle) => set({ D, error: null }))
      .catch((e: Error) => set({ D: null, error: e.message }))
  }, [])
  return state
}

export default function App() {
  const { D, error } = useBundle()
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light'))
  const toggleTheme = () => {
    const next: Theme = theme === 'dark' ? 'light' : 'dark'
    setTheme(next)
    document.documentElement.dataset.theme = next
    document.documentElement.style.colorScheme = next
    try { localStorage.setItem(THEME_KEY, next) } catch { /* storage may be blocked */ }
  }
  const [view, setViewRaw] = useState<View>(() => {
    const h = location.hash.slice(1)
    return VIEWS.some((v) => v.id === h) ? (h as View) : 'overview'
  })
  const setView = (v: View) => { setViewRaw(v); history.replaceState(null, '', '#' + v) }
  const [picker, setPicker] = useState(false)
  const [tri, setTri] = useState(true)
  const [log, setLog] = useState(true)
  const [runId, setRunId] = useState<string | null>(null)
  const [compare, setCompareRaw] = useState<string[] | null>(null)
  const [preset, setPreset] = useState('all')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [book, setBook] = useState(0)
  const core = useMemo(() => (D ? createCore(D) : null), [D])
  const closePicker = useCallback(() => setPicker(false), [])
  const id = D ? runId ?? D.runs[0].id : ''
  // Until the user chooses, compare the run listed next in the config.
  const cmp = D ? (compare ?? D.runs.slice(1, 2).map((r) => r.id)).filter((x) => x !== id).slice(0, MAX_COMPARE) : []

  return (
    <div className="h-full flex flex-col overflow-hidden">
      <TopBar view={view} setView={(v) => { setView(v); setPicker(false) }} dataTo={D?.data_to ?? ''} run={D && core ? core.run(id) : null}
        compared={cmp.length} openPicker={() => setPicker(true)} theme={theme} toggleTheme={toggleTheme} />
      <main className="grow min-h-0 py-5 flex flex-col gap-5" style={{ paddingInline: 'clamp(16px, 4.4vw, 64px)' }}>
        {error && (
          <div className="grow flex flex-col items-center justify-center gap-2 text-center">
            <span className="text-[13px] font-semibold">Could not load the run records</span>
            <span className="text-xs text-faint">{error}</span>
            <code className="text-xs text-soft">uv run mb dashboard export configs/dashboard/research.yaml</code>
          </div>
        )}
        {!error && !D && (
          <div className="grow flex flex-col items-center justify-center gap-3 text-faint">
            <span className="w-10 h-10 rounded-full border border-border bg-s2" />
            <span className="text-[13px] font-semibold text-ink">Loading run records</span>
            <span className="text-xs">Equity, trades and prices for every strategy</span>
          </div>
        )}
        {D && core && (() => {
          const run = core.run(id)
          const rg: Range = preset === 'custom' ? core.customRange(from, to, run) : core.presetRange(preset, run)
          const [i0, i1] = rg
          const span = core.span(run)
          const c: Ctx = {
            D, core, run, compare: cmp, i0, i1, tri, log, setTri, setLog, setCompare: setCompareRaw, openPicker: () => setPicker(true),
            where: `run ${run.id} · ${run.config}`,
          }
          const dates = `${fdate(D.cal[i0])} → ${fdate(D.cal[i1])} (${((Date.parse(D.cal[i1]) - Date.parse(D.cal[i0])) / (365.25 * 864e5)).toFixed(1)} yrs)`
          const pb = D.paper.books[Math.min(book, D.paper.books.length - 1)]
          const HEAD: Record<View, [string, string, string]> = {
            overview: ['BACKTEST · ' + run.group.toUpperCase(), run.label, `${c.where} · ${dates}`],
            trades: ['BACKTEST · TRADES', 'Every trade, with its chart', `${c.where} · ${dates}`],
            metrics: ['BACKTEST · METRICS', 'All metrics for the selected dates', `Re-sliced from the recorded equity, not re-run · ${c.where}`],
            monthly: ['BACKTEST · CALENDAR', 'Monthly returns', `${c.where} · ${dates}`],
            compare: ['RESEARCH · COMPARE', 'Strategies side by side', `Same dates for every line · primary ${c.where}`],
            paper: ['LIVE · PAPER TRADING', 'Paper book · ' + (pb?.label ?? ''), pb ? `${pb.config} · starts ${fdate(pb.start)}` : 'No paper book configured'],
          }
          const [eyebrow, title, desc] = HEAD[view]
          return (
            <>
              <PageHead eyebrow={eyebrow} title={title} desc={desc}>
                {view !== 'paper' ? (
                  <DateRange presets={core.presets} active={preset} custom={preset === 'custom'} from={D.cal[i0]} to={D.cal[i1]} min={D.cal[span[0]]} max={D.cal[span[1]]}
                    onPreset={setPreset} onFrom={(v) => { setFrom(v); setTo(preset === 'custom' ? to : D.cal[i1]); setPreset('custom') }}
                    onTo={(v) => { setTo(v); setFrom(preset === 'custom' ? from : D.cal[i0]); setPreset('custom') }} />
                ) : pb ? <PaperHeadToggle c={c} book={book} setBook={setBook} /> : null}
              </PageHead>
              {view === 'overview' && <Overview c={c} />}
              {view === 'trades' && <Trades key={run.id} c={c} />}
              {view === 'metrics' && <Metrics c={c} />}
              {view === 'monthly' && <Monthly c={c} />}
              {view === 'compare' && <Compare c={c} />}
              {view === 'paper' && pb && <Paper c={c} book={book} />}
              {picker && (
                <Picker D={D} primary={id} compare={cmp} onClose={closePicker} onCompare={setCompareRaw}
                  onPick={(x) => { setRunId(x); setCompareRaw(cmp.filter((y) => y !== x)); setPicker(false) }} />
              )}
            </>
          )
        })()}
      </main>
    </div>
  )
}
