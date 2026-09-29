import { Calendar, ChevronDown, FileText, GitCompare, LayoutDashboard, Moon, Sun, TrendingUp, ArrowLeftRight, BarChart3 } from 'lucide-react'
import type { ReactNode } from 'react'
import { fdate } from '../lib/format'
import type { Run } from '../lib/types'
import { Badge, tagTone } from '../lib/ui'
import { shortLabel } from '../lib/series'

export type View = 'overview' | 'trades' | 'metrics' | 'monthly' | 'compare' | 'paper'
export const VIEWS: { id: View; label: string; icon: ReactNode }[] = [
  { id: 'overview', label: 'Overview', icon: <LayoutDashboard size={14} /> },
  { id: 'trades', label: 'Trades', icon: <ArrowLeftRight size={14} /> },
  { id: 'metrics', label: 'Metrics', icon: <BarChart3 size={14} /> },
  { id: 'monthly', label: 'Monthly', icon: <Calendar size={14} /> },
  { id: 'compare', label: 'Compare', icon: <GitCompare size={14} /> },
  { id: 'paper', label: 'Paper', icon: <FileText size={14} /> },
]

export function TopBar({ view, setView, dataTo, run, compared, openPicker, theme, toggleTheme }: {
  view: View; setView: (v: View) => void; dataTo: string; run: Run | null; compared: number
  openPicker: () => void; theme: 'light' | 'dark'; toggleTheme: () => void
}) {
  return (
    <header className="h-14 flex-none px-6 flex items-center gap-7 border-b border-border backdrop-blur-md" style={{ background: 'var(--topbar)' }}>
      <div className="flex items-center gap-2.5">
        <span className="relative w-8 h-8 rounded-lg bg-accent flex items-center justify-center shadow-[var(--shadow-sm)]">
          <TrendingUp size={17} color="#fff" strokeWidth={2.2} />
          <span className="absolute -right-0.5 -top-0.5 w-[9px] h-[9px] rounded-full bg-up border-2 border-surface" />
        </span>
        <span className="flex flex-col gap-px">
          <span className="text-[13px] font-bold tracking-[-0.01em]">Multibagger</span>
          <span className="text-[9px] font-semibold tracking-[0.16em] text-faint">RESEARCH TERMINAL</span>
        </span>
      </div>
      <nav className="flex gap-0.5 p-[3px] rounded-[10px] border border-border bg-s2">
        {VIEWS.map((v) => {
          const on = v.id === view
          return (
            <button key={v.id} onClick={() => setView(v.id)} aria-current={on ? 'page' : undefined}
              className={`h-7 px-[11px] rounded-[7px] flex items-center gap-[7px] text-xs font-semibold ${on ? 'bg-surface text-accent shadow-[var(--pill)]' : 'text-soft'}`}>
              {v.icon}{v.label}
            </button>
          )
        })}
      </nav>
      <div className="ml-auto flex items-center gap-2.5">
        <span className="h-[26px] px-[9px] rounded-[7px] border border-border bg-surface flex items-center gap-1.5 text-[11px] font-medium text-soft">
          <span className="w-1.5 h-1.5 rounded-full bg-up" />Data to {fdate(dataTo)}
        </span>
        {run && (
          <button onClick={openPicker} className="h-[34px] pl-3 pr-2 rounded-[9px] border border-border bg-surface shadow-[var(--shadow-sm)] flex items-center gap-[9px] text-xs font-semibold max-w-[420px]">
            <span className="w-2 h-2 rounded-full bg-accent flex-none" />
            <span className="truncate">{shortLabel(run.label)}</span>
            <Badge tone={tagTone(run.tag)}>{run.tag}</Badge>
            {compared > 0 && <span className="text-[11px] font-medium text-faint whitespace-nowrap">+{compared} compared</span>}
            <ChevronDown size={14} className="text-faint flex-none" />
          </button>
        )}
        <button onClick={toggleTheme} aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          className="w-[34px] h-[34px] rounded-[9px] border border-border bg-surface flex items-center justify-center text-soft">
          {theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </div>
    </header>
  )
}
