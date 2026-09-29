import { useMemo } from 'react'
import { EquityPanel } from '../components/EquityPanel'
import type { Ctx } from '../lib/ctx'
import { COMPARE_ROWS } from '../lib/summary'
import { buildSeries, colorOf, MAX_COMPARE, shortLabel } from '../lib/series'
import { Toggle } from '../lib/ui'
import { fdate } from '../lib/format'
import type { Metrics } from '../lib/core'

export function Compare({ c }: { c: Ctx }) {
  const { core, run, compare, i0, i1, tri, log, D } = c
  const series = useMemo(() => buildSeries(core, run.id, compare, tri), [core, run.id, compare, tri])
  const cols = useMemo(() => {
    const items: { id: string; label: string; color: string; m: Metrics | null }[] = [run.id, ...compare].map((id) => {
      const r = core.run(id)
      return { id, label: shortLabel(r.label), color: colorOf(id, run.id, compare), m: core.metrics(r, i0, i1) }
    })
    if (tri) items.push({ id: 'tri', label: 'Nifty 500 TRI', color: 'var(--faint)', m: core.metrics(core.bench, i0, i1) })
    return items
  }, [core, run.id, compare, i0, i1, tri])
  const rows = COMPARE_ROWS.map(([label, key, fmt, dir]) => {
    const vals = cols.map((x) => (x.m ? (x.m[key] as number | null) : null))
    let best = -1
    if (dir) vals.forEach((v, k) => {
      if (v === null || !isFinite(v)) return
      if (best < 0 || v * dir > (vals[best] as number) * dir) best = k
    })
    return { label, cells: vals.map((v, k) => ({ text: fmt(v), best: k === best && vals.length > 1 })) }
  })
  return (
    <>
      <EquityPanel core={core} series={series} i0={i0} i1={i1} log={log} drawdown={false} locked={false} className="grow basis-0 min-h-[190px]"
        head={() => (
          <>
            <div className="flex flex-col gap-0.5"><span className="text-[13px] font-semibold">Equity, rebased to the first day</span><span className="text-[11px] text-faint">Up to {MAX_COMPARE} strategies against the primary</span></div>
            <div className="flex items-center gap-2">
              <span className="h-7 px-2.5 rounded-lg border border-border bg-s2 flex items-center gap-[7px] text-[11px] font-semibold"><span className="w-2 h-2 rounded-full bg-accent" />{shortLabel(run.label)}<span className="font-medium text-faint">primary</span></span>
              {compare.map((id) => (
                <span key={id} className="h-7 pl-2.5 pr-1 rounded-lg border border-border bg-surface flex items-center gap-[7px] text-[11px] font-semibold">
                  <span className="w-2 h-2 rounded-full" style={{ background: colorOf(id, run.id, compare) }} />{shortLabel(core.run(id).label)}
                  <button onClick={() => c.setCompare(compare.filter((x) => x !== id))} aria-label="Stop comparing" className="w-5 h-5 rounded-[5px] text-center text-faint text-[13px]">×</button>
                </span>
              ))}
              <button onClick={c.openPicker} className="h-7 px-3 rounded-lg bg-accent text-white text-[11px] font-semibold shadow-[var(--shadow-sm)]">+ Add strategy</button>
              <div className="flex gap-0.5 p-0.5 rounded-lg border border-border bg-s2">
                <Toggle on={tri} onClick={() => c.setTri(!tri)}>TRI</Toggle>
                <Toggle on={log} onClick={() => c.setLog(!log)}>Log</Toggle>
              </div>
            </div>
          </>
        )} />
      <div className="card flex-none overflow-hidden grid content-start" style={{ gridTemplateColumns: `240px repeat(${cols.length}, minmax(0, 1fr))` }}>
        <span className="h-[52px] px-4 flex flex-col justify-center gap-0.5 bg-s2 border-b border-border"><span className="text-[13px] font-semibold">Metric</span><span className="text-[11px] text-faint">{fdate(D.cal[i0])} → {fdate(D.cal[i1])}</span></span>
        {cols.map((x) => (
          <span key={x.id} className="h-[52px] px-4 flex flex-col justify-center items-end gap-0.5 bg-s2 border-b border-border">
            <span className="flex items-center gap-[7px] text-xs font-semibold"><span className="w-2 h-2 rounded-full" style={{ background: x.color }} />{x.label}</span>
            <span className="text-[10px] text-faint">{x.m ? `${x.m.start.slice(0, 4)}–${x.m.end.slice(0, 4)}` : '—'}</span>
          </span>
        ))}
        {rows.flatMap((r) => [
          <span key={r.label} className="h-[29px] px-4 flex items-center border-b border-row-line text-xs font-medium text-soft">{r.label}</span>,
          ...r.cells.map((cl, k) => (
            <span key={r.label + k} className="h-[29px] px-4 flex items-center justify-end border-b border-row-line text-xs font-semibold" style={{ color: cl.best ? 'var(--up)' : 'var(--ink)' }}>
              <span className="px-1.5 py-px rounded-[5px]" style={{ background: cl.best ? 'var(--up-soft)' : 'transparent' }}>{cl.text}</span>
            </span>
          )),
        ])}
      </div>
    </>
  )
}
