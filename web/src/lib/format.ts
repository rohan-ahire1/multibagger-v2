// Number and date formatting, as in the approved mockup.
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export const MONTHS = MON

export type Tone = 'gain' | 'loss' | 'flat'
type N = number | null | undefined
const ok = (v: N): v is number => v !== null && v !== undefined && isFinite(v)

export function fdate(iso: string | null | undefined): string {
  if (!iso) return '—'
  return +iso.slice(8, 10) + ' ' + MON[+iso.slice(5, 7) - 1] + ' ' + iso.slice(0, 4)
}
export function fdateShort(iso: string): string {
  return MON[+iso.slice(5, 7) - 1] + ' ’' + iso.slice(2, 4)
}
export function pct(v: N, d = 1): string {
  if (!ok(v)) return '—'
  return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(d) + '%'
}
export function pctPlain(v: N, d = 1): string {
  if (!ok(v)) return '—'
  return (v < 0 ? '−' : '') + Math.abs(v).toFixed(d) + '%'
}
export function num(v: N, d = 2): string {
  if (!ok(v)) return '—'
  return (v < 0 ? '−' : '') + Math.abs(v).toFixed(d)
}
export function inr(v: N): string {
  if (!ok(v)) return '—'
  const a = Math.abs(v), s = v < 0 ? '−₹' : '₹'
  if (a >= 1e7) return s + (a / 1e7).toFixed(2) + ' Cr'
  if (a >= 1e5) return s + (a / 1e5).toFixed(2) + ' L'
  return s + Math.round(a).toLocaleString('en-IN')
}
export function inrSigned(v: number): string {
  return (v > 0 ? '+' : '') + inr(v)
}
export function tone(v: N): Tone {
  return v !== null && v !== undefined && v > 0 ? 'gain' : v !== null && v !== undefined && v < 0 ? 'loss' : 'flat'
}
export function int(v: N): string {
  return ok(v) ? v.toLocaleString('en-IN') : '—'
}
export function fmtPx(v: N): string {
  if (!v) return '—'
  return v >= 1000 ? Math.round(v).toLocaleString('en-IN') : v >= 100 ? v.toFixed(0) : v.toFixed(1)
}
export function rupeePx(v: N): string {
  return v ? '₹' + v.toLocaleString('en-IN') : '—'
}
export function toneColor(t: Tone): string {
  return t === 'gain' ? 'var(--up)' : t === 'loss' ? 'var(--down)' : 'var(--ink)'
}
export function shade(rgbVar: string, strength: number): string {
  return `rgba(var(${rgbVar}),${(0.06 + 0.64 * strength).toFixed(3)})`
}
