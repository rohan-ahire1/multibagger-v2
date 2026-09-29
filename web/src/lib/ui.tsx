// Small shared pieces: sizing hook, segmented control, badge, card head.
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

export function useSize<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  const [size, set] = useState({ w: 0, h: 0 })
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const measure = () => {
      const w = Math.round(el.clientWidth), h = Math.round(el.clientHeight)
      set((p) => (p.w === w && p.h === h ? p : { w, h }))
    }
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  return [ref, size] as const
}

export type BadgeTone = 'up' | 'down' | 'warn' | 'accent' | 'neutral'
const BADGE: Record<BadgeTone, string> = {
  up: 'bg-up-soft text-up border-up-border', down: 'bg-down-soft text-down border-down-border',
  warn: 'bg-warn-soft text-warn border-warn-border', accent: 'bg-accent-soft text-accent border-accent-border',
  neutral: 'bg-s2 text-soft border-border',
}
export const tagTone = (tag: string): BadgeTone => (/paper/i.test(tag) ? 'accent' : /final|locked/i.test(tag) ? 'warn' : 'neutral')

export function Badge({ tone = 'neutral', children, className = '' }: { tone?: BadgeTone; children: ReactNode; className?: string }) {
  return <span className={`inline-block rounded-[5px] border px-1.5 py-px text-[10px] font-semibold whitespace-nowrap ${BADGE[tone]} ${className}`}>{children}</span>
}

const SEG = {
  lg: { box: 'p-[3px] rounded-[10px]', btn: 'h-7 px-[11px] rounded-[7px] text-xs gap-[7px]' },
  md: { box: 'p-[3px] rounded-[10px]', btn: 'h-[26px] px-[9px] rounded-[7px] text-[11px]' },
  book: { box: 'p-[3px] rounded-[10px]', btn: 'h-7 px-3.5 rounded-[7px] text-xs' },
  sm: { box: 'p-0.5 rounded-lg', btn: 'h-[22px] px-2 rounded-md text-[11px]' },
  side: { box: 'p-0.5 rounded-lg', btn: 'h-6 px-2.5 rounded-md text-[11px]' },
}
export function Seg<T extends string>({ items, value, onChange, size = 'md', className = '' }: {
  items: { id: T; label: ReactNode }[]; value: T | null; onChange: (id: T) => void; size?: keyof typeof SEG; className?: string
}) {
  const z = SEG[size]
  return (
    <div className={`flex gap-0.5 border border-border bg-s2 ${z.box} ${className}`}>
      {items.map((it) => {
        const on = it.id === value
        return (
          <button key={it.id} onClick={() => onChange(it.id)} aria-pressed={on}
            className={`flex items-center font-semibold whitespace-nowrap ${z.btn} ${on ? 'bg-surface text-accent shadow-[var(--pill)]' : 'text-soft'}`}>
            {it.label}
          </button>
        )
      })}
    </div>
  )
}

export function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick} aria-pressed={on}
      className={`h-[22px] px-2 rounded-md text-[11px] font-semibold ${on ? 'bg-surface text-accent shadow-[var(--pill)]' : 'text-soft'}`}>{children}</button>
  )
}

export function CardTitle({ title, sub, className = '' }: { title: ReactNode; sub?: ReactNode; className?: string }) {
  return (
    <div className={`flex flex-col gap-0.5 min-w-0 ${className}`}>
      <span className="text-[13px] font-semibold">{title}</span>
      {sub ? <span className="text-[11px] text-faint">{sub}</span> : null}
    </div>
  )
}

export const Label = ({ children, className = '' }: { children: ReactNode; className?: string }) => (
  <span className={`text-[10px] font-semibold tracking-[0.08em] uppercase text-faint ${className}`}>{children}</span>
)
