import { useMemo } from 'react'
import { Badge, CardTitle, useSize } from '../lib/ui'
import { Empty } from './Overview'
import type { Ctx } from '../lib/ctx'
import { num, pct, toneColor } from '../lib/format'
import { recNum } from '../lib/core'
import { summary } from '../lib/summary'

export function Metrics({ c }: { c: Ctx }) {
  const { core, run, i0, i1, D } = c
  const s = useMemo(() => summary(core, run, i0, i1), [core, run, i0, i1])
  const [hRef, hs] = useSize<HTMLDivElement>()
  if (!s) return <Empty />
  const hist = hs.w > 0 ? core.histogram(run, i0, i1, hs.w, hs.h) : []
  const key = D.adoption_metric
  const metricName = key === 'calmar' ? 'Calmar' : 'CAGR'
  const cell = (r: Record<string, unknown> | undefined) => (r ? recNum(r as never, key) : null)
  const bl = run.baselines
  const foldRows = [...D.folds.map(([name, start, end]) => ({ k: name, label: `${start.slice(0, 4)}–${end.slice(2, 4)}` })), { k: 'period', label: 'Whole run' }]
    .map(({ k, label }) => {
      const st = k === 'period' ? run.metrics : run.folds[k]
      const mo = bl.momentum_12_1?.[k], tr = bl.nifty500_tri_buy_and_hold?.[k]
      if (!st || !mo || !tr) return null
      const a = cell(st), b = cell(mo), t = cell(tr)
      return { label, cagr: recNum(st, 'cagr_pct'), calmar: recNum(st, 'calmar'), mo: recNum(mo, 'calmar'), tri: recNum(tr, 'calmar'), pass: a !== null && b !== null && t !== null && a > b && a > t }
    })
    .filter((x): x is NonNullable<typeof x> => x !== null)
  const GRID = 'grid-cols-[1.4fr_1fr_1fr_1fr_1fr_1fr]'
  return (
    <>
      <div className="flex-none grid grid-cols-4 gap-5">
        {s.groups.map((g) => (
          <div key={g.title} className="card px-4 pb-2 h-[352px] box-border overflow-hidden">
            <div className="h-11 flex items-center text-[13px] font-semibold">{g.title}</div>
            {g.items.map((it) => (
              <div key={it.label} className="h-[30px] flex justify-between items-center gap-2.5 border-t border-row-line text-xs">
                <span className="text-soft truncate">{it.label}</span>
                <span className="font-semibold whitespace-nowrap" style={{ color: toneColor(it.tone) }}>{it.value}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="flex-1 min-h-0 grid grid-cols-[minmax(0,757fr)_minmax(0,535fr)] gap-5">
        <div className="card overflow-hidden flex flex-col min-h-0">
          <div className="h-14 flex-none px-4 flex items-center">
            <CardTitle title="Walk-forward folds" sub={`${metricName} against both baselines · whole run as recorded, not the date filter`} />
          </div>
          <div className={`h-7 flex-none px-4 grid ${GRID} items-center border-y border-border bg-s2 text-[9.5px] font-semibold tracking-[0.08em] text-faint`}>
            <span>WINDOW</span><span className="text-right">CAGR</span><span className="text-right">CALMAR</span><span className="text-right">12-1 CALMAR</span><span className="text-right">TRI CALMAR</span><span className="text-right">VERDICT</span>
          </div>
          <div className="grow min-h-0 overflow-y-auto">
            {foldRows.map((f) => (
              <div key={f.label} className={`h-10 px-4 grid ${GRID} items-center border-b border-row-line text-xs`}>
                <span className="font-semibold">{f.label}</span>
                <span className="text-right text-soft">{pct(f.cagr, 1)}</span>
                <span className="text-right font-semibold">{num(f.calmar, 2)}</span>
                <span className="text-right text-faint">{num(f.mo, 2)}</span>
                <span className="text-right text-faint">{num(f.tri, 2)}</span>
                <span className="text-right"><Badge tone={f.pass ? 'up' : 'down'}>{f.pass ? 'Beats both' : 'Behind'}</Badge></span>
              </div>
            ))}
            {foldRows.length === 0 && <div className="px-4 py-8 text-xs text-faint">No fold record for this run.</div>}
          </div>
        </div>
        <div className="card px-4 flex flex-col min-h-0">
          <div className="h-14 flex-none flex flex-col justify-center"><CardTitle title="Return per trade" sub="Number of trades in each return bucket, %" /></div>
          <div ref={hRef} className="relative grow min-h-[60px] mt-2 border-b border-border">
            {hist.map((b) => (
              <div key={b.label} className="absolute rounded-t opacity-80" title={`${b.label}: ${b.n}`} style={{ left: b.x, top: b.top, width: b.w, height: b.h, background: toneColor(b.tone === 'loss' ? 'loss' : 'gain') }} />
            ))}
          </div>
          <div className="relative flex-none h-3.5 mt-1.5 mb-3.5">
            {hist.map((b) => <span key={b.label} className="absolute text-center text-[9px] text-faint" style={{ left: b.x, width: b.w }}>{b.label}</span>)}
          </div>
        </div>
      </div>
    </>
  )
}
