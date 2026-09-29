import { useMemo } from 'react'
import { Empty } from './Overview'
import type { Ctx } from '../lib/ctx'
import { MONTHS, pct, pctPlain, shade, toneColor } from '../lib/format'
import { CardTitle } from '../lib/ui'

const COLS = 'grid-cols-[52px_repeat(12,minmax(0,1fr))_72px_minmax(120px,200px)]'

export function Monthly({ c }: { c: Ctx }) {
  const { core, run, i0, i1 } = c
  const heat = useMemo(() => core.heatmap(run, i0, i1), [core, run, i0, i1])
  const m = useMemo(() => core.metrics(run, i0, i1), [core, run, i0, i1])
  if (!m) return <Empty />
  const mx = Math.max(1, ...heat.map((h) => Math.abs(h.totalV)))
  const stats = [
    { label: 'POSITIVE MONTHS', value: pctPlain(m.posMonths, 0) + ' of ' + m.months, color: 'var(--ink)' },
    { label: 'BEST', value: pct(m.bestMonth, 1), color: 'var(--up)' },
    { label: 'WORST', value: pct(m.worstMonth, 1), color: 'var(--down)' },
  ]
  return (
    <div className="card grow min-h-0 px-5 pb-4 flex flex-col">
      <div className="h-[60px] flex-none flex items-center justify-between">
        <CardTitle title="Monthly returns, %" sub="Darker cells are bigger moves · bar on the right is the calendar year" />
        <div className="flex rounded-[10px] border border-border bg-tint">
          {stats.map((k, i) => (
            <div key={k.label} className={`px-3.5 py-1.5 flex flex-col gap-px ${i ? 'border-l border-border' : ''}`}>
              <span className="text-[9.5px] font-semibold tracking-[0.08em] text-faint">{k.label}</span>
              <span className="text-[13px] font-semibold" style={{ color: k.color }}>{k.value}</span>
            </div>
          ))}
        </div>
      </div>
      <div className={`grid ${COLS} gap-1 pb-1.5 text-[10px] font-semibold tracking-[0.06em] text-faint flex-none`}>
        <span />{MONTHS.map((mo) => <span key={mo} className="text-center">{mo}</span>)}<span className="text-right">YEAR</span><span />
      </div>
      <div className="grow min-h-0 overflow-y-auto">
        {heat.map((row) => {
          const w = (Math.abs(row.totalV) / mx) * 62, neg = row.totalV < 0
          return (
            <div key={row.year} className={`grid ${COLS} gap-1 mb-1 text-[11px]`}>
              <span className="flex items-center font-semibold text-soft">{row.year}</span>
              {row.cells.map((cl, k) => (
                <span key={k} className="h-[25px] rounded-[5px] flex items-center justify-center font-medium"
                  style={{
                    background: cl.tone === 'none' || cl.tone === 'flat' ? 'transparent' : shade(cl.tone === 'gain' ? '--up-rgb' : '--down-rgb', cl.strength),
                    color: cl.strength > 0.55 && (cl.tone === 'gain' || cl.tone === 'loss') ? 'var(--strong-text)' : 'var(--ink)',
                  }}>{cl.text}</span>
              ))}
              <span className="flex items-center justify-end font-bold" style={{ color: toneColor(row.tone) }}>{row.total}</span>
              <span className="relative h-[25px]">
                <span className="absolute top-[3px] bottom-[3px] border-l border-bstrong" style={{ left: '35%' }} />
                <span className="absolute top-2 h-[9px] rounded-[3px] opacity-85" style={{ background: toneColor(row.tone), width: Math.min(Math.max(w, 0.5), neg ? 33 : 62) + '%', left: neg ? `calc(35% - ${Math.min(Math.max(w, 0.5), 33)}%)` : '35%' }} />
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
