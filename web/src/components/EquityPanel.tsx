import { useMemo, useState, type ReactNode } from 'react'
import type { Core, Line, SeriesIn } from '../lib/core'
import { useSize } from '../lib/ui'

const GUTTER = 44

// Equity lines rebased to the first day of the window, optional drawdown pane, locked-test band and hover tooltip.
// The drawing area follows the size of its box, so the chart fills whatever the layout gives it.
export function EquityPanel({ core, series, i0, i1, log, drawdown, locked, head, className = '' }: {
  core: Core; series: SeriesIn[]; i0: number; i1: number; log: boolean; drawdown: boolean; locked: boolean
  head: (lines: Line[]) => ReactNode; className?: string
}) {
  const [plotRef, { w, h }] = useSize<HTMLDivElement>()
  const [ddRef, { h: ddH }] = useSize<HTMLDivElement>()
  const [hx, setHx] = useState<number | null>(null)
  const chart = useMemo(
    () => (w > 10 && h > 10 ? core.equityChart(series, i0, i1, w, h, drawdown ? Math.max(10, ddH) : 0, log) : null),
    [core, series, i0, i1, w, h, ddH, log, drawdown],
  )
  const hv = chart && hx !== null ? core.hover(chart, series, hx, w) : null
  const lock = chart && locked ? core.band(i0, i1, core.idxAtOrAfter(core.D.locked_from), i1, w) : null
  let area = ''
  if (chart && chart.lines[0]) {
    const d = chart.lines[0].d
    const xs = d.match(/^M([\d.-]+) /), xe = d.match(/L([\d.-]+) [\d.-]+$/)
    if (xs && xe) area = `${d}L${xe[1]} ${h}L${xs[1]} ${h}Z`
  }
  return (
    <div className={`card flex flex-col px-4 pb-3.5 min-h-0 ${className}`}>
      <div className="h-14 flex-none flex items-center justify-between gap-4">{head(chart?.lines ?? [])}</div>
      <div ref={plotRef} className="relative flex-1 min-h-[80px]" style={{ marginLeft: GUTTER }}
        onMouseMove={(e) => { const b = e.currentTarget.getBoundingClientRect(); setHx(Math.max(0, Math.min(w, e.clientX - b.left))) }}
        onMouseLeave={() => setHx(null)}>
        {lock?.show && (
          <>
            <div className="absolute top-0 bottom-0 border-l border-dashed border-bstrong" style={{ left: lock.x, width: lock.w, background: 'var(--lock-band)' }} />
            <span className="absolute top-1.5 pl-2 text-[9px] font-semibold tracking-[0.12em] text-faint" style={{ left: lock.x }}>LOCKED TEST</span>
          </>
        )}
        {chart?.grid.map((g, k) => (
          <div key={k}>
            <div className="absolute left-0 right-0 border-t" style={{ top: g.y, borderColor: 'var(--grid)' }} />
            <span className="absolute w-9 text-right text-[10px] text-faint -translate-y-1/2" style={{ left: -GUTTER, top: g.y }}>{g.label}</span>
          </div>
        ))}
        {chart && (
          <svg width={w} height={h} className="absolute left-0 top-0 overflow-visible pointer-events-none">
            {area && drawdown && <path d={area} style={{ fill: 'var(--accent-fill)' }} />}
            {chart.lines.map((l, k) => (
              <path key={k} d={l.d} fill="none" stroke={l.color} strokeWidth={l.width} strokeLinejoin="round" strokeDasharray={l.dash || undefined} />
            ))}
          </svg>
        )}
        {hv && (
          <>
            <div className="absolute top-0 bottom-0 border-l border-bstrong pointer-events-none" style={{ left: hv.x }} />
            <div className="absolute top-2.5 w-[196px] px-3 py-2.5 rounded-[10px] bg-surface border border-border flex flex-col gap-1.5 pointer-events-none"
              style={{ left: hv.x > w - 220 ? hv.x - 208 : hv.x + 14, boxShadow: 'var(--shadow-float)' }}>
              <span className="text-[11px] font-semibold text-soft">{hv.date}</span>
              {hv.rows.map((r, k) => (
                <span key={k} className="flex items-center gap-[7px] text-[11px]">
                  <span className="w-[7px] h-[7px] rounded-full flex-none" style={{ background: r.color }} />
                  <span className="grow text-soft truncate">{r.label}</span>
                  <span className="font-semibold">{r.text}</span>
                </span>
              ))}
            </div>
          </>
        )}
      </div>
      <div className="relative flex-none h-[22px]" style={{ marginLeft: GUTTER }}>
        {chart?.ticks.map((t, k) => (
          <span key={k} className="absolute top-1.5 -translate-x-1/2 text-[10px] text-faint whitespace-nowrap" style={{ left: t.x }}>{t.label}</span>
        ))}
      </div>
      {drawdown && (
        <div ref={ddRef} className="relative flex-none h-[72px] border-t border-border" style={{ marginLeft: GUTTER }}>
          <span className="absolute top-0.5 w-9 text-right text-[10px] text-faint" style={{ left: -GUTTER }}>0%</span>
          <span className="absolute bottom-0 w-9 text-right text-[10px] text-faint" style={{ left: -GUTTER }}>{chart?.ddFloorLabel}</span>
          {chart && (
            <svg width={w} height={ddH} className="absolute left-0 top-0">
              <path d={chart.dd} style={{ fill: 'var(--down-fill)', stroke: 'var(--down)', strokeWidth: 1 }} />
            </svg>
          )}
          <span className="absolute right-0 bottom-1 text-[10px] font-semibold tracking-[0.08em] text-faint">DRAWDOWN · WORST {chart?.ddLabel}</span>
        </div>
      )}
    </div>
  )
}
