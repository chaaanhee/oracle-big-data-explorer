import type { Cell } from './types'

const nf = new Intl.NumberFormat('ko-KR')

export function fmtInt(n: number | null | undefined): string {
  return n === null || n === undefined ? '-' : nf.format(n)
}

export function fmtPct(r: number | null | undefined, digits = 1): string {
  if (r === null || r === undefined) return '-'
  if (r > 0 && r < 0.001) return '<0.1%'
  return `${(r * 100).toFixed(digits)}%`
}

export function fmtBytes(b: number | null | undefined): string {
  if (b === null || b === undefined) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let v = b
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '-'
  return ms < 1000 ? `${ms.toFixed(0)} ms` : `${(ms / 1000).toFixed(2)} s`
}

export function fmtCell(v: Cell | undefined): string {
  if (v === null || v === undefined) return 'NULL'
  return String(v)
}

export function fmtDate(s: string | null | undefined): string {
  return s ? s.slice(0, 16) : '-'
}

export function daysAgo(s: string | null | undefined): string {
  if (!s) return ''
  const d = (Date.now() - new Date(s.replace(' ', 'T')).getTime()) / 86_400_000
  if (d < 1) return '오늘'
  if (d < 31) return `${Math.floor(d)}일 전`
  if (d < 365) return `${Math.floor(d / 30)}개월 전`
  return `${(d / 365).toFixed(1)}년 전`
}

export function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e)
}
