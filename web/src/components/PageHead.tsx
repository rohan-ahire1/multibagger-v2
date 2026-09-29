import { Calendar } from 'lucide-react'
import type { ReactNode } from 'react'

// Page title block: eyebrow, title, and one line that always names the config file and run id.
export function PageHead({ eyebrow, title, desc, children }: { eyebrow: string; title: string; desc: string; children?: ReactNode }) {
  return (
    <div className="h-16 flex-none flex items-end justify-between gap-6">
      <div className="flex flex-col gap-[5px] min-w-0">
        <span className="text-[10px] font-semibold tracking-[0.14em] text-accent">{eyebrow}</span>
        <span className="text-[22px] font-semibold tracking-[-0.035em] leading-[1.1] truncate">{title}</span>
        <span className="text-xs text-faint truncate" title={desc}>{desc}</span>
      </div>
      {children}
    </div>
  )
}

export function DateRange({ presets, active, custom, from, to, min, max, onPreset, onFrom, onTo }: {
  presets: { id: string; label: string }[]; active: string; custom: boolean; from: string; to: string; min: string; max: string
  onPreset: (id: string) => void; onFrom: (v: string) => void; onTo: (v: string) => void
}) {
  return (
    <div className="flex items-center gap-2.5 flex-none" title="Metrics are re-sliced from the recorded equity for these dates. The strategy is not re-run.">
      <div className="flex gap-0.5 p-[3px] rounded-[10px] border border-border bg-s2">
        {presets.map((p) => {
          const on = !custom && p.id === active
          return (
            <button key={p.id} onClick={() => onPreset(p.id)} aria-pressed={on}
              className={`h-[26px] px-[9px] rounded-[7px] text-[11px] font-semibold ${on ? 'bg-surface text-accent shadow-[var(--pill)]' : 'text-soft'}`}>{p.label}</button>
          )
        })}
      </div>
      <div className={`h-[34px] pl-2.5 pr-1 rounded-[9px] border bg-surface flex items-center gap-1 ${custom ? 'border-accent' : 'border-border'}`}>
        <Calendar size={14} className="text-faint" />
        <label><span className="sr-only">From</span>
          <input type="date" value={from} min={min} max={max} onChange={(e) => e.target.value && onFrom(e.target.value)} className="h-7 w-[112px] px-1 border-0 bg-transparent text-xs font-medium" style={{ colorScheme: 'inherit' }} />
        </label>
        <span className="text-faint text-xs">→</span>
        <label><span className="sr-only">To</span>
          <input type="date" value={to} min={min} max={max} onChange={(e) => e.target.value && onTo(e.target.value)} className="h-7 w-[112px] px-1 border-0 bg-transparent text-xs font-medium" style={{ colorScheme: 'inherit' }} />
        </label>
      </div>
    </div>
  )
}
