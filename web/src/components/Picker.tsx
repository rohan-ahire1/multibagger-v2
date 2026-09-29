import { Check } from 'lucide-react'
import { useEffect } from 'react'
import { num, pctPlain } from '../lib/format'
import { recNum } from '../lib/core'
import { colorOf, MAX_COMPARE, shortLabel } from '../lib/series'
import type { Bundle } from '../lib/types'
import { Badge, tagTone } from '../lib/ui'

export function Picker({ D, primary, compare, onPick, onCompare, onClose }: {
  D: Bundle; primary: string; compare: string[]; onPick: (id: string) => void; onCompare: (ids: string[]) => void; onClose: () => void
}) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  return (
    <>
      <button aria-label="Close strategy list" onClick={onClose} className="fixed inset-0 z-40 backdrop-blur-[2px]" style={{ background: 'var(--overlay)' }} />
      <div role="dialog" aria-label="Strategies" className="fixed z-50 left-1/2 -translate-x-1/2 top-24 w-[640px] max-w-[94vw] max-h-[calc(100vh-120px)] rounded-2xl border border-border bg-surface flex flex-col overflow-hidden"
        style={{ boxShadow: 'var(--shadow-float)' }}>
        <div className="h-16 flex-none pl-5 pr-3 flex items-center justify-between border-b border-border">
          <div className="flex flex-col gap-0.5">
            <span className="text-sm font-semibold">Strategies</span>
            <span className="text-[11px] text-faint">Click a row to open it · tick up to {MAX_COMPARE} to compare</span>
          </div>
          <button onClick={onClose} aria-label="Close" className="h-[26px] px-2 rounded-md border border-border bg-s2 font-mono text-[10px] text-faint">esc</button>
        </div>
        <div className="h-7 flex-none pl-5 pr-3 grid grid-cols-[1fr_64px_64px_56px_36px] items-center bg-s2 border-b border-border text-[9.5px] font-semibold tracking-[0.08em] text-faint">
          <span /><span className="text-right">CAGR</span><span className="text-right">MAX DD</span><span className="text-right">CALMAR</span><span />
        </div>
        <div className="grow overflow-y-auto pt-1 px-1.5 pb-2.5">
          {D.groups.map((g) => (
            <div key={g}>
              <div className="pt-3 px-3.5 pb-1 text-[10px] font-semibold tracking-[0.1em] uppercase text-faint">{g}</div>
              {D.runs.filter((r) => r.group === g).map((r) => {
                const active = r.id === primary, on = compare.includes(r.id)
                const color = colorOf(r.id, primary, compare)
                return (
                  <div key={r.id} className={`grid grid-cols-[1fr_36px] items-center rounded-lg ${active ? 'bg-accent-soft' : ''}`}>
                    <button onClick={() => onPick(r.id)} title={r.note || undefined} className="h-10 pl-3.5 grid grid-cols-[16px_1fr_64px_64px_56px] items-center text-[12.5px]">
                      <span className="w-2 h-2 rounded-full" style={{ background: active ? 'var(--accent)' : on ? color : 'var(--bstrong)' }} />
                      <span className={`flex items-center gap-[7px] min-w-0 ${active ? 'font-semibold text-accent' : 'font-medium'}`}>
                        <span className="truncate">{shortLabel(r.label)}</span>
                        <Badge tone={tagTone(r.tag)} className="flex-none !text-[9.5px] !px-[5px] !py-0 !rounded-[4px]">{r.tag}</Badge>
                      </span>
                      <span className="text-right text-xs font-semibold">{pctPlain(recNum(r.metrics, 'cagr_pct'), 1)}</span>
                      <span className="text-right text-xs text-soft">{pctPlain(recNum(r.metrics, 'max_dd_pct') === null ? null : -(recNum(r.metrics, 'max_dd_pct') as number), 1)}</span>
                      <span className="text-right text-xs text-soft">{num(recNum(r.metrics, 'calmar'), 2)}</span>
                    </button>
                    {!active && (
                      <button onClick={() => onCompare(on ? compare.filter((x) => x !== r.id) : compare.concat(r.id).slice(-MAX_COMPARE))}
                        aria-label={(on ? 'Stop comparing ' : 'Compare ') + shortLabel(r.label)} aria-pressed={on} className="w-9 h-10 flex items-center justify-center">
                        <span className="w-[15px] h-[15px] box-border rounded-[4px] border-[1.5px] flex items-center justify-center"
                          style={{ borderColor: on ? color : 'var(--bstrong)', background: on ? color : 'transparent' }}>
                          {on && <Check size={11} color="#fff" strokeWidth={3} />}
                        </span>
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
