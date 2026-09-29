import type { Core } from './core'
import type { Bundle, Run } from './types'

// What every view gets from the app shell.
export interface Ctx {
  D: Bundle
  core: Core
  run: Run
  compare: string[]
  i0: number
  i1: number
  tri: boolean
  log: boolean
  setTri: (v: boolean) => void
  setLog: (v: boolean) => void
  setCompare: (ids: string[]) => void
  openPicker: () => void
  where: string
}
