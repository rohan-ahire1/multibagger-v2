import type { Core, SeriesIn } from './core'

const VARS = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)']
export const MAX_COMPARE = 3

export const shortLabel = (label: string) => {
  const k = label.indexOf(' · ')
  return k >= 0 ? label.slice(k + 3) : label
}
export function colorOf(id: string, primary: string, compare: string[]): string {
  return id === primary ? 'var(--accent)' : VARS[Math.max(0, compare.indexOf(id)) % VARS.length]
}
// Lines for the equity chart: the primary run, the compared runs, then the index.
export function buildSeries(core: Core, primary: string, compare: string[], tri: boolean): SeriesIn[] {
  const r = core.run(primary)
  const out: SeriesIn[] = [{ label: shortLabel(r.label), values: r.equity, color: 'var(--accent)', width: 2 }]
  for (const id of compare) {
    const x = core.run(id)
    out.push({ label: shortLabel(x.label), values: x.equity, color: colorOf(id, primary, compare), width: 1.4 })
  }
  if (tri) out.push({ label: 'Nifty 500 TRI', values: core.bench.equity, color: 'var(--faint)', width: 1.25, dash: '4 4' })
  return out
}
