import { Seg, Badge, CardTitle, Label } from '../lib/ui'
import type { Ctx } from '../lib/ctx'
import { fdate, fdateShort, inr, num, pct, pctPlain, tone, toneColor } from '../lib/format'
import type { PaperBook, PaperLive } from '../lib/types'

export function bookRun(c: Ctx, b: PaperBook) {
  const { core } = c
  const r = core.run(b.backtest_run)
  const s = core.span(r)
  const full = core.metrics(r, s[0], s[1])
  const lk = core.idxAtOrAfter(core.D.locked_from)
  const locked = s[1] > lk ? core.metrics(r, lk, s[1]) : null
  return { r, full, locked }
}

export function PaperHeadToggle({ c, book, setBook }: { c: Ctx; book: number; setBook: (n: number) => void }) {
  return <Seg size="book" items={c.D.paper.books.map((b, k) => ({ id: String(k), label: b.label }))} value={String(book)} onChange={(v) => setBook(+v)} />
}

export function Paper({ c, book }: { c: Ctx; book: number }) {
  const { D, core } = c
  const b = D.paper.books[Math.min(book, D.paper.books.length - 1)]
  const { r, full, locked } = bookRun(c, b)
  const live = b.live
  const pv = b.preview
  const fundN = pv.picks.filter((p) => core.isFund(p[0])).length
  const sectorOf = (sym: string) => { const i = D.symbols.indexOf(sym); return i >= 0 && D.sectors[i] ? D.sectors[i] : core.isFund(sym) ? 'Fund unit' : '—' }
  const stats = [
    live
      ? { label: 'Status', value: 'Live', sub: 'as of ' + fdate(live.as_of), fg: 'var(--up)' }
      : { label: 'Status', value: 'Armed', sub: b.first_decision ? 'first decision ' + fdate(b.first_decision) : 'no decision date', fg: 'var(--accent)' },
    live
      ? { label: 'Equity', value: inr(live.equity), sub: `${pct(live.return_pct, 1)} since start · ${live.positions.length} positions`, fg: 'var(--ink)' }
      : { label: 'Equity', value: inr(b.capital), sub: 'all cash · 0 positions', fg: 'var(--ink)' },
    { label: 'Backtest CAGR', value: pct(full?.cagr, 1), sub: full ? fdateShort(full.start) + ' – ' + fdateShort(full.end) : '', fg: 'var(--ink)' },
    { label: 'Max DD · Calmar', value: pctPlain(full?.mdd, 1) + ' · ' + num(full?.calmar, 2), sub: 'backtest, same config', fg: 'var(--ink)' },
    { label: 'Locked test CAGR', value: locked ? pct(locked.cagr, 1) : '—', sub: locked ? `${D.locked_from.slice(0, 4)} → latest data` : 'this book is its test', fg: 'var(--ink)' },
    { label: 'Backtest run', value: r.id, sub: b.strategy, fg: 'var(--soft)', mono: true },
  ]
  return (
    <>
      <div className="card flex-none overflow-hidden grid grid-cols-6">
        {stats.map((k, i) => (
          <div key={k.label} className={`px-4 pt-[13px] pb-3 flex flex-col gap-[3px] min-w-0 ${i ? 'border-l border-border' : ''}`}>
            <Label>{k.label}</Label>
            <span className={`font-semibold tracking-[-0.02em] truncate ${k.mono ? 'text-[13px] font-mono' : 'text-[21px]'}`} style={{ color: k.fg }}>{k.value}</span>
            <span className="text-[11px] text-faint truncate">{k.sub}</span>
          </div>
        ))}
      </div>
      <div className="flex-1 min-h-0 grid grid-cols-[minmax(0,868fr)_minmax(0,424fr)] gap-5">
        {live ? <LiveBook live={live} /> : (
          <div className="card px-4 pb-3.5 flex flex-col min-h-0">
            <div className="h-14 flex-none flex items-center justify-between gap-3">
              <CardTitle title={`Target book if the month ended ${fdate(pv.as_of)}`} sub={`Ranked by the strategy · 12-1 momentum shown · about ${inr(b.capital / pv.n)} per name`} />
              <Badge>Preview</Badge>
            </div>
            {fundN > 0 && <div className="flex-none mb-2.5 px-3 py-[9px] rounded-lg border border-warn-border bg-warn-soft text-warn text-xs font-medium">{fundN} of {pv.n} picks are fund units.</div>}
            <div className="grow min-h-0 overflow-y-auto">
              <div className="grid grid-cols-4 gap-x-[18px]">
                {pv.picks.map((p, k) => (
                  <div key={p[0]} className="h-11 flex flex-col justify-center gap-0.5 border-t border-row-line min-w-0">
                    <span className="flex justify-between gap-1.5 text-xs">
                      <span className="truncate"><span className="inline-block w-5 text-faint">{k + 1}</span><span className="font-semibold text-accent">{p[0]}</span></span>
                      <span className="font-semibold" style={{ color: tone(p[2]) === 'loss' ? 'var(--down)' : 'var(--up)' }}>{pct(p[2], 1)}</span>
                    </span>
                    <span className="pl-5 text-[10.5px] text-faint truncate">{sectorOf(p[0])}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="flex-none pt-2.5 border-t border-border text-[11px] text-faint">Next in line: <span className="font-semibold text-soft">{pv.bench.join(' · ')}</span></div>
          </div>
        )}
        <Steps b={b} live={live} />
      </div>
    </>
  )
}

function Steps({ b, live }: { b: PaperBook; live: PaperLive | null }) {
  const pv = b.preview
  const steps: { when: string; what: string; detail: string; state: 'done' | 'next' | 'todo' }[] = [
    { when: fdate(pv.as_of), what: 'Preview', detail: 'Ranking if the month ended at this close', state: 'done' },
    { when: (b.first_decision ? fdate(b.first_decision) : 'First month-end') + ' · after close', what: 'First decision', detail: 'Rank at the close, write the order ticket', state: live && live.decisions > 0 ? 'done' : 'next' },
    { when: 'Next session · open', what: 'Fills', detail: 'Buys fill at the open with costs and slippage', state: live && live.fills.length ? 'done' : 'todo' },
    { when: 'Every weekday evening', what: 'Mark to market', detail: b.timer + '. Alerts on ntfy', state: live && live.sessions > 0 ? 'done' : 'todo' },
    { when: 'Last session of each month', what: 'Rebalance', detail: `Sell names that dropped out, buy the new top ${pv.n}`, state: 'todo' },
    { when: 'After each month-end', what: 'Replay check', detail: 'Backtest the same days; equity gap must stay under 2%', state: 'todo' },
  ]
  return (
    <div className="card px-4 pb-2 flex flex-col min-h-0 overflow-y-auto">
      <div className="h-14 flex-none flex flex-col justify-center gap-0.5"><span className="text-[13px] font-semibold">How a day runs</span><span className="text-[11px] text-faint">{b.timer} · alerts on ntfy</span></div>
      {steps.map((s) => (
        <div key={s.what} className="grid grid-cols-[22px_1fr] gap-2.5 py-[11px] border-t border-row-line">
          <span className="w-3 h-3 mt-0.5 rounded-full border-2"
            style={{ background: s.state === 'done' ? 'var(--up)' : s.state === 'next' ? 'var(--accent)' : 'var(--surface)', borderColor: s.state === 'done' ? 'var(--up)' : s.state === 'next' ? 'var(--accent)' : 'var(--bstrong)', boxShadow: s.state === 'next' ? '0 0 0 4px var(--accent-soft)' : 'none' }} />
          <div className="flex flex-col gap-0.5">
            <span className="flex justify-between gap-2 text-[12.5px] font-semibold">{s.what}<span className="text-[10.5px] font-medium" style={{ color: s.state === 'next' ? 'var(--accent)' : 'var(--faint)' }}>{s.when}</span></span>
            <span className="text-[11.5px] text-faint">{s.detail}</span>
          </div>
        </div>
      ))}
      {live && live.fills.length > 0 && (
        <div className="pt-3 border-t border-border">
          <Label>Recent fills</Label>
          {live.fills.slice(-6).reverse().map((f, k) => (
            <div key={k} className="flex justify-between text-[11px] py-1"><span className="text-soft">{fdate(f.session)} · {f.side} {f.symbol}</span><span className="font-medium">{f.shares} @ {f.price.toLocaleString('en-IN')}</span></div>
          ))}
        </div>
      )}
    </div>
  )
}

function LiveBook({ live }: { live: PaperLive }) {
  const pts = live.curve
  const lo = Math.min(...pts.map((p) => p[1])), hi = Math.max(...pts.map((p) => p[1]))
  const path = pts.length > 1 ? pts.map((p, i) => `${i ? 'L' : 'M'}${((i / (pts.length - 1)) * 100).toFixed(2)} ${(100 - ((p[1] - lo) / Math.max(1, hi - lo)) * 100).toFixed(2)}`).join('') : ''
  return (
    <div className="card px-4 pb-3.5 flex flex-col min-h-0">
      <div className="h-14 flex-none flex items-center justify-between gap-3">
        <CardTitle title={`Positions as of ${fdate(live.as_of)}`} sub={`${live.sessions} sessions · ${live.decisions} decisions · cash ${inr(live.cash)}${live.pending ? ` · ${live.pending} orders pending` : ''}`} />
        <Badge tone="up">Live</Badge>
      </div>
      {path && (
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="flex-none h-24 w-full mb-2.5"><path d={path} fill="none" stroke="var(--accent)" strokeWidth={1.5} vectorEffect="non-scaling-stroke" /></svg>
      )}
      <div className="h-7 flex-none grid grid-cols-[1.2fr_0.8fr_1fr_1fr_1fr_0.8fr_0.8fr] gap-2 items-center border-y border-border bg-s2 px-2 text-[9.5px] font-semibold tracking-[0.08em] text-faint">
        <span>SYMBOL</span><span className="text-right">SHARES</span><span>BOUGHT</span><span className="text-right">CLOSE</span><span className="text-right">VALUE</span><span className="text-right">WEIGHT</span><span className="text-right">GAIN</span>
      </div>
      <div className="grow min-h-0 overflow-y-auto">
        {live.positions.map((p) => (
          <div key={p.symbol} className="h-[34px] px-2 grid grid-cols-[1.2fr_0.8fr_1fr_1fr_1fr_0.8fr_0.8fr] gap-2 items-center border-b border-row-line text-xs">
            <span className="font-semibold text-accent">{p.symbol}</span><span className="text-right text-soft">{p.shares.toLocaleString('en-IN')}</span><span className="text-soft">{fdate(p.entry)}</span>
            <span className="text-right">{p.close.toLocaleString('en-IN')}</span><span className="text-right">{inr(p.value)}</span><span className="text-right text-soft">{pctPlain(p.weight_pct, 1)}</span>
            <span className="text-right font-semibold" style={{ color: toneColor(tone(p.gain_pct)) }}>{pct(p.gain_pct, 1)}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
