import { useMemo } from 'react'
import { EquityPanel } from '../components/EquityPanel'
import { Badge } from '../lib/ui'
import { Toggle, Label, CardTitle, useSize } from '../lib/ui'
import { num, pct, pctPlain, toneColor } from '../lib/format'
import type { Ctx } from '../lib/ctx'
import { buildSeries } from '../lib/series'
import { summary } from '../lib/summary'

export function Overview({ c }: { c: Ctx }) {
  const { core, run, i0, i1, compare, tri, log } = c
  const s = useMemo(() => summary(core, run, i0, i1), [core, run, i0, i1])
  const series = useMemo(() => buildSeries(core, run.id, compare, tri), [core, run.id, compare, tri])
  const [barsRef, bars] = useSize<HTMLDivElement>()
  if (!s) return <Empty />
  const { m, bm } = s
  const ex = bm ? m.cagr - bm.cagr : null
  const ahead = ex !== null && ex > 0
  const pair = (label: string, a: number | null, b: number | null | undefined, f: (v: number | null | undefined) => string) => {
    const mx = Math.max(Math.abs(a || 0), Math.abs(b || 0)) || 1
    return { label, a: f(a), b: f(b) + ' TRI', aW: Math.max(2, (Math.abs(a || 0) / mx) * 100) + '%', bW: Math.max(2, (Math.abs(b || 0) / mx) * 100) + '%' }
  }
  const rows = [pair('CAGR', m.cagr, bm?.cagr, (v) => pct(v, 1)), pair('Max drawdown', m.mdd, bm?.mdd, (v) => pctPlain(v, 1)), pair('Calmar', m.calmar, bm?.calmar, (v) => num(v, 2))]
  const years = bars.w > 0 ? core.yearlyBars(run, i0, i1, bars.w, bars.h) : []
  return (
    <>
      <div className="card flex-none overflow-hidden">
        <div className="grid grid-cols-6">
          {s.kpis.map((k, i) => (
            <div key={k.label} className={`px-4 pt-[13px] pb-3 flex flex-col gap-[3px] ${i ? 'border-l border-border' : ''}`}>
              <Label>{k.label}</Label>
              <span className="text-[21px] font-semibold tracking-[-0.02em]" style={{ color: toneColor(k.tone) }}>{k.value}</span>
              <span className="text-[11px] text-faint truncate">{k.sub}</span>
            </div>
          ))}
        </div>
        <div className="grid grid-cols-6 border-t border-border bg-tint">
          {s.extras.map((k, i) => (
            <div key={k.label} className={`px-4 py-2.5 flex flex-col gap-0.5 ${i ? 'border-l border-border' : ''}`}>
              <Label>{k.label}</Label>
              <span className="text-sm font-semibold" style={{ color: toneColor(k.tone) }}>{k.value}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 grid grid-cols-[minmax(0,868fr)_minmax(0,424fr)] gap-5">
        <EquityPanel core={core} series={series} i0={i0} i1={i1} log={log} drawdown locked
          head={(lines) => (
            <>
              <CardTitle title="Equity curve" sub={`Growth of ₹1 · ${log ? 'log' : 'linear'} scale · hover for values`} />
              <div className="flex items-center gap-3.5">
                {lines.map((l) => (
                  <span key={l.label} className="flex items-center gap-1.5 text-[11px] font-medium text-soft whitespace-nowrap">
                    <span className="w-3.5 border-t-2" style={{ borderTopStyle: l.dash ? 'dashed' : 'solid', borderTopColor: l.color }} />{l.label}
                    <span className="font-semibold text-ink">{l.endText}</span>
                  </span>
                ))}
                <div className="flex gap-0.5 p-0.5 rounded-lg border border-border bg-s2">
                  <Toggle on={tri} onClick={() => c.setTri(!tri)}>TRI</Toggle>
                  <Toggle on={log} onClick={() => c.setLog(!log)}>Log</Toggle>
                </div>
              </div>
            </>
          )} />

        <div className="flex flex-col gap-5 min-h-0">
          <div className="card relative flex-none overflow-hidden px-[18px] pt-[18px] pb-4 flex flex-col gap-3.5">
            <span className="absolute inset-x-0 top-0 h-0.5" style={{ background: 'linear-gradient(90deg, var(--accent), var(--up))' }} />
            <div className="flex justify-between items-start">
              <div className="flex flex-col gap-1">
                <span className="text-[10px] font-semibold tracking-[0.1em] text-faint">EXCESS CAGR VS NIFTY 500 TRI</span>
                <span className="text-[28px] font-semibold tracking-[-0.03em]" style={{ color: ahead ? 'var(--up)' : 'var(--down)' }}>{ex === null ? '—' : pct(ex, 2)}</span>
              </div>
              <Badge tone={ahead ? 'up' : 'down'}>{ahead ? 'Ahead of the index' : 'Behind the index'}</Badge>
            </div>
            {rows.map((r) => (
              <div key={r.label} className="flex flex-col gap-[5px]">
                <div className="flex justify-between text-[11px]">
                  <span className="text-soft font-medium">{r.label}</span>
                  <span className="text-faint"><span className="font-semibold text-ink">{r.a}</span> vs {r.b}</span>
                </div>
                <div className="h-[5px] rounded-[3px] bg-s2"><div className="h-[5px] rounded-[3px] bg-accent" style={{ width: r.aW }} /></div>
                <div className="h-[5px] rounded-[3px] bg-s2"><div className="h-[5px] rounded-[3px] bg-bstrong" style={{ width: r.bW }} /></div>
              </div>
            ))}
          </div>

          <div className="card grow min-h-0 px-4 flex flex-col">
            <div className="h-[52px] flex-none flex items-center"><CardTitle title="Calendar years" sub="Return per year in the selected dates" /></div>
            <div ref={barsRef} className="relative grow min-h-[60px] mt-1">
              <div className="absolute inset-x-0 border-t border-border" style={{ top: bars.h / 2 }} />
              {years.map((y) => (
                <div key={y.year} className="absolute rounded-[3px] opacity-85" style={{ left: y.x, top: y.top, width: y.w, height: y.h, background: toneColor(y.tone) }} title={`${y.year} ${y.text}`} />
              ))}
            </div>
            <div className="relative flex-none h-4 mt-1.5 mb-3.5">
              {years.map((y) => <span key={y.year} className="absolute text-center text-[9px] text-faint" style={{ left: y.x, width: y.w }}>{y.year}</span>)}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}

export function Empty({ text = 'No equity in the selected dates.' }: { text?: string }) {
  return <div className="grow flex items-center justify-center text-[13px] text-faint">{text}</div>
}
