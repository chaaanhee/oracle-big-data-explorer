import { useCallback, useEffect, useState } from 'react'
import type { TableRef } from './types'

const PREFIX = 'oracle-explorer:'

function read<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(PREFIX + key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

/** 같은 키를 쓰는 모든 컴포넌트가 함께 갱신되는 localStorage 상태. */
export function useStored<T>(key: string, fallback: T): [T, (update: (prev: T) => T) => void] {
  const [value, setValue] = useState<T>(() => read(key, fallback))

  useEffect(() => {
    const sync = (e: Event) => {
      if ((e as CustomEvent<string>).detail === key) setValue(read(key, fallback))
    }
    window.addEventListener('stored-change', sync)
    return () => window.removeEventListener('stored-change', sync)
  }, [key])

  const update = useCallback(
    (fn: (prev: T) => T) => {
      const next = fn(read(key, fallback))
      localStorage.setItem(PREFIX + key, JSON.stringify(next))
      setValue(next)
      window.dispatchEvent(new CustomEvent('stored-change', { detail: key }))
    },
    [key],
  )
  return [value, update]
}

const same = (a: TableRef, b: TableRef) => a.owner === b.owner && a.name === b.name

export function useFavorites() {
  const [favorites, setFavorites] = useStored<TableRef[]>('favorites', [])
  const isFavorite = (t: TableRef) => favorites.some((f) => same(f, t))
  const toggleFavorite = (t: TableRef) =>
    setFavorites((prev) =>
      prev.some((f) => same(f, t)) ? prev.filter((f) => !same(f, t)) : [...prev, { owner: t.owner, name: t.name }],
    )
  return { favorites, isFavorite, toggleFavorite }
}

export interface RecentTable extends TableRef {
  at: number
}

export function useRecent() {
  const [recent, setRecent] = useStored<RecentTable[]>('recent', [])
  const touch = useCallback(
    (t: TableRef) =>
      setRecent((prev) => [{ owner: t.owner, name: t.name, at: Date.now() }, ...prev.filter((r) => !same(r, t))].slice(0, 20)),
    [setRecent],
  )
  const clear = () => setRecent(() => [])
  return { recent, touch, clear }
}

export interface HistoryItem {
  id: string
  sql: string
  at: number
  ok: boolean
  rows?: number
  elapsed_ms?: number
  error?: string
}

export interface SavedQuery {
  id: string
  name: string
  sql: string
  at: number
}

export const newId = () => Math.random().toString(36).slice(2, 10) + Date.now().toString(36)
