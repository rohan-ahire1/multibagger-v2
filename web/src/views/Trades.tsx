import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Badge, Seg, useSize, type BadgeTone } from '../lib/ui'
import type { Ctx } from '../lib/ctx'
import { fdate, toneColor } from '../lib/format'
import type { TradeQuery } from '../lib/core'

const STATUS_TONE: Record<string, BadgeTone> = { open: 'accent', stopped: 'down', intraday_stop: 'down' }
const COLS = 'grid-cols-[1.5fr_1.1fr_1.1fr_0.55fr_1.15fr_0.8fr_0.95fr]'
const SIDES = [{ id: 'all', label: 'All' }, { id: 'win', label: 'Winners' }, { id: 'loss', label: 'Losers' }] as const

export function Trades({ c }: { c: Ctx }) {
  const { core, run, i0, i1, D } = c
  const [q, setQ] = useState('')
  const [side, setSide] = useState<'all' | 'win' | 'loss'>('all')
  const [sort, setSort] = useState<NonNullable<TradeQuery['sort']>>('entry')
  const [dir, setDir] = useState<'asc' | 'desc'>('desc')
  const [page, setPage] = useState(0)
  const [trade, setTrade] = useState<number | null>(null)
  const size = D.ui.page_size
  const tq = useMemo(() => core.trades(run, i0, i1, { q, side, sort, dir, page, size }), [core, run, i0, i1, q, side, sort, dir, page, size])
  const sel = trade !== null && run.trades[trade] && tq.order.includes(trade) ? trade : tq.order.length ? tq.order[tq.page * tq.size] : null
  const pos = sel === null ? -1 : tq.order.indexOf(sel)
  const go = (k: number) => { const j = pos + k; if (j >= 0 && j < tq.order.length) { setTrade(tq.order[j]); setPage(Math.floor(j / tq.size)) } }
  const sortBy = (k: typeof sort) => { setDir(sort === k && dir === 'desc' ? 'asc' : 'desc'); setSort(k); setPage(0) }
  const arrow = (k: typeof sort) => (sort === k ? (dir === 'desc' ? ' ↓' : ' ↑') : '')
  const reset = () => { setPage(0); setTrade(null) }
  return (
    <div className="flex-1 min-h-0 grid grid-cols-[minmax(0,792fr)_minmax(0,500fr)] gap-5">
      <div className="card flex flex-col overflow-hidden min-h-0">
        <div className="h-[58px] flex-none px-4 flex items-center justify-between gap-3">
          <div className="flex flex-col gap-0.5 min-w-0">
            <span className="flex items-center gap-2 text-[13px] font-semibold">Trades<Badge>{tq.total.toLocaleString('en-IN')}</Badge></span>
            <span className="text-[11px] text-faint truncate">Opened between {fdate(core.D.cal[i0])} and {fdate(core.D.cal[i1])}</span>
          </div>
          <div className="flex items-center gap-2">
            <Seg size="side" items={SIDES.map((s) => ({ id: s.id, label: s.label }))} value={side} onChange={(v) => { setSide(v); reset() }} />
            <label className="h-[30px] w-[150px] px-2.5 rounded-lg border border-border bg-surface flex items-center gap-1.5">
              <Search size={13} className="text-faint flex-none" />
              <span className="sr-only">Search symbol</span>
              <input type="search" placeholder="Symbol" value={q} onChange={(e) => { setQ(e.target.value); reset() }} className="w-full border-0 bg-transparent text-xs outline-none" />
            </label>
          </div>
        </div>
        <div className={`h-[30px] flex-none px-4 grid ${COLS} gap-2.5 items-center border-y border-border bg-s2 text-[9.5px] font-semibold tracking-[0.08em] text-faint`}>
          <button onClick={() => sortBy('sym')}>SYMBOL{arrow('sym')}</button>
          <button onClick={() => sortBy('entry')}>BOUGHT{arrow('entry')}</button>
          <span>SOLD</span>
          <button onClick={() => sortBy('hold')} className="text-right">DAYS{arrow('hold')}</button>
          <span>EXIT</span>
          <button onClick={() => sortBy('ret')} className="text-right">RETURN{arrow('ret')}</button>
          <button onClick={() => sortBy('pnl')} className="text-right">P&amp;L{arrow('pnl')}</button>
        </div>
        <div className="grow min-h-0 overflow-y-auto">
          {tq.rows.map((r) => {
            const active = r.i === sel
            return (
              <button key={r.key} onClick={() => setTrade(r.i)} aria-pressed={active}
                className={`h-[38px] w-full px-4 grid ${COLS} gap-2.5 items-center border-b border-row-line text-xs`}
                style={{ background: active ? 'var(--accent-soft)' : r.tone === 'gain' ? 'var(--up-row)' : r.tone === 'loss' ? 'var(--down-row)' : 'transparent', boxShadow: active ? 'inset 3px 0 0 var(--accent)' : 'none' }}>
                <span className="flex flex-col gap-px min-w-0"><span className="font-semibold text-accent">{r.sym}</span><span className="text-[10px] text-faint truncate">{r.sector}</span></span>
                <span className="text-soft">{r.entry}</span>
                <span className="text-soft">{r.exit}</span>
                <span className="text-right text-faint">{r.hold}</span>
                <span><Badge tone={STATUS_TONE[r.statusKey] ?? 'neutral'}>{r.status}</Badge></span>
                <span className="text-right font-semibold" style={{ color: toneColor(r.tone) }}>{r.ret}</span>
                <span className="text-right font-medium" style={{ color: toneColor(r.tone) }}>{r.pnl}</span>
              </button>
            )
          })}
          {tq.total === 0 && (
            <div className="py-12 flex flex-col items-center gap-1.5"><span className="text-[13px] font-semibold">No trades match</span><span className="text-xs text-faint">Try another symbol, side or date range.</span></div>
          )}
        </div>
        <div className="h-[46px] flex-none px-4 flex items-center justify-between border-t border-border text-[11px] text-faint">
          <span>{tq.total ? `${tq.page * tq.size + 1}–${Math.min(tq.total, (tq.page + 1) * tq.size)} of ${tq.total.toLocaleString('en-IN')}` : '0 trades'}</span>
          <span className="flex gap-1.5">
            {[['Previous', -1, tq.page <= 0], ['Next', 1, tq.page >= tq.pages - 1]].map(([label, k, off]) => (
              <button key={label as string} disabled={off as boolean} onClick={() => { setPage(Math.max(0, Math.min(tq.pages - 1, tq.page + (k as number)))); setTrade(null) }}
                className="h-7 px-2.5 rounded-lg border border-border bg-surface text-[11px] font-semibold text-soft">{label}</button>
            ))}
          </span>
        </div>
      </div>
      <Rail c={c} sel={sel} pos={pos} total={tq.order.length} go={go} pick={(i) => { const j = tq.order.indexOf(i); setTrade(i); if (j >= 0) setPage(Math.floor(j / tq.size)) }} />
    </div>
  )
}

function Rail({ c, sel, pos, total, go, pick }: { c: Ctx; sel: number | null; pos: number; total: number; go: (k: number) => void; pick: (i: number) => void }) {
  const { core, run } = c
  const [ref, { w, h }] = useSize<HTMLDivElement>()
  const tc = sel !== null && w > 10 && h > 10 ? core.tradeChart(run, sel, w, h) : null
  const row = sel !== null ? core.tradeRow(run, sel) : null
  if (!row) return <div className="card p-5 flex flex-col items-center justify-center gap-1.5"><span className="text-[13px] font-semibold">No chart</span><span className="text-xs text-faint">Pick a trade on the left.</span></div>
  const up = run.trades[sel as number][4] > 0
  const fg = up ? 'var(--up)' : 'var(--down)', rgb = up ? '--up-rgb' : '--down-rgb'
  const note = run.px_source === 'dataset' ? 'Prices are the dataset’s adjusted open on the fill dates; this run does not record them.' : ''
  return (
    <div className="card min-h-0 px-5 pt-[18px] pb-4 flex flex-col gap-3.5">
      <div className="flex justify-between items-start flex-none">
        <div className="flex flex-col gap-1 min-w-0">
          <span className="flex items-center gap-2 text-xl font-semibold tracking-[-0.02em]">{row.sym}<Badge tone={STATUS_TONE[row.statusKey] ?? 'neutral'} className="tracking-normal">{row.status}</Badge></span>
          <span className="text-xs text-faint">{row.sector} · weekly close, adjusted</span>
        </div>
        <div className="flex flex-col items-end gap-0.5">
          <span className="text-2xl font-semibold tracking-[-0.02em]" style={{ color: fg }}>{row.ret}</span>
          <span className="text-xs font-medium" style={{ color: fg }}>{row.pnl}</span>
        </div>
      </div>
      <div ref={ref} className="relative grow min-h-[120px] mt-1.5 mr-14">
        {tc ? (
          <>
            <div className="absolute top-0 bottom-0" style={{ left: tc.hold.x, width: tc.hold.w, background: `rgba(var(${rgb}),0.09)` }} />
            {tc.grid.map((g, k) => (
              <div key={k}>
                <div className="absolute left-0 right-0 border-t" style={{ top: g.y, borderColor: 'var(--grid)' }} />
                <span className="absolute -translate-y-1/2 text-[10px] text-faint whitespace-nowrap" style={{ left: w + 8, top: g.y }}>{g.label}</span>
              </div>
            ))}
            <div className="absolute border-t border-dashed border-bstrong" style={{ left: tc.entryLine.x, width: tc.entryLine.w, top: tc.entryLine.y }} />
            <svg width={w} height={h} className="absolute left-0 top-0 overflow-visible"><path d={tc.d} fill="none" stroke="var(--ink)" strokeWidth={1.5} strokeLinejoin="round" /></svg>
            <div className="absolute w-2.5 h-2.5 -ml-[7px] -mt-[7px] rounded-full bg-surface border-2 border-accent" style={{ left: tc.entry.x, top: tc.entry.y }} />
            {run.px_source === 'recorded' || run.trades[sel as number][8] ? (
              <span className="absolute text-[10px] font-semibold text-accent whitespace-nowrap pr-1.5" style={{ left: tc.entry.x, top: tc.entry.y, transform: 'translate(-100%, 8px)' }}>Buy {tc.entry.text}</span>
            ) : null}
            <div className="absolute w-2.5 h-2.5 -ml-[7px] -mt-[7px] rounded-full border-2 border-surface" style={{ left: tc.exit.x, top: tc.exit.y, background: fg, boxShadow: `0 0 0 1px ${fg}` }} />
            <div className="absolute w-[74px] h-6 rounded-[7px] flex items-center justify-center text-xs font-semibold text-white" style={{ left: tc.label.x, top: tc.label.y, background: fg, boxShadow: '0 4px 12px rgba(16,24,40,0.12)' }}>{tc.label.text}</div>
          </>
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-xs text-faint">No weekly prices for this name.</div>
        )}
      </div>
      <div className="relative flex-none h-3.5 mr-14">
        {tc?.ticks.map((t, k) => <span key={k} className="absolute -translate-x-1/2 text-[10px] text-faint whitespace-nowrap" style={{ left: t.x }}>{t.label}</span>)}
      </div>
      {tc && tc.others.length > 0 && (
        <div className="flex flex-col gap-1.5 flex-none">
          <span className="text-[10px] font-semibold tracking-[0.08em] text-faint">OTHER TRADES IN THIS NAME</span>
          <div className="relative h-5 mr-14">
            {tc.others.map((x) => (
              <button key={x.idx} onClick={() => pick(x.idx)} className="absolute h-5 rounded-[5px] text-center text-[10px] font-semibold overflow-hidden"
                style={{ left: x.x, width: x.w, color: x.tone === 'gain' ? 'var(--up)' : 'var(--down)', background: `rgba(var(${x.tone === 'gain' ? '--up-rgb' : '--down-rgb'}),0.16)` }}>{x.text}</button>
            ))}
          </div>
        </div>
      )}
      <div className="flex-none mt-auto grid grid-cols-3 rounded-[10px] border border-border bg-tint">
        {[['BOUGHT', row.entryPx, row.entry], ['SOLD', row.exitPx, row.exit], ['POSITION', row.size, 'held ' + row.hold]].map(([l, a, b], k) => (
          <div key={l} className={`px-3.5 py-2.5 flex flex-col gap-0.5 ${k ? 'border-l border-border' : ''}`}>
            <span className="text-[10px] font-semibold tracking-[0.08em] text-faint">{l}</span>
            <span className="text-sm font-semibold">{a}</span>
            <span className="text-[11px] text-faint">{b}</span>
          </div>
        ))}
      </div>
      {note && <span className="flex-none text-[10.5px] text-faint leading-snug">{note}</span>}
      <div className="flex-none flex justify-between items-center">
        <span className="text-[11px] text-faint">Trade {pos + 1} / {total.toLocaleString('en-IN')}</span>
        <span className="flex gap-1.5">
          <button disabled={pos <= 0} onClick={() => go(-1)} className="h-[30px] px-3 rounded-lg border border-border bg-surface text-xs font-semibold text-soft">‹ Previous</button>
          <button disabled={pos >= total - 1} onClick={() => go(1)} className="h-[30px] px-3 rounded-lg border border-border bg-surface text-xs font-semibold text-soft">Next ›</button>
        </span>
      </div>
    </div>
  )
}
