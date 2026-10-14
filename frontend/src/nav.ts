import { useEffect, useState } from 'react'

export type TableTab = 'data' | 'structure' | 'profile' | 'relations'

export type Route =
  | { view: 'explorer'; owner?: string }
  | { view: 'table'; owner: string; name: string; tab: TableTab }
  | { view: 'sql' }
  | { view: 'map'; owner?: string; focus?: string }
  | { view: 'search'; q?: string }

const TABS: TableTab[] = ['data', 'structure', 'profile', 'relations']

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent)
  switch (parts[0]) {
    case 'table':
      if (parts[1] && parts[2]) {
        const tab = TABS.includes(parts[3] as TableTab) ? (parts[3] as TableTab) : 'data'
        return { view: 'table', owner: parts[1], name: parts[2], tab }
      }
      break
    case 'sql':
      return { view: 'sql' }
    case 'map':
      return { view: 'map', owner: parts[1] || undefined, focus: parts[2] || undefined }
    case 'search':
      return { view: 'search', q: parts[1] || undefined }
    case 'explorer':
      return { view: 'explorer', owner: parts[1] || undefined }
  }
  return { view: 'explorer' }
}

export function href(r: Route): string {
  const e = encodeURIComponent
  switch (r.view) {
    case 'table':
      return `#/table/${e(r.owner)}/${e(r.name)}/${r.tab}`
    case 'sql':
      return '#/sql'
    case 'map':
      return `#/map${r.owner ? `/${e(r.owner)}` : ''}${r.owner && r.focus ? `/${e(r.focus)}` : ''}`
    case 'search':
      return `#/search${r.q ? `/${e(r.q)}` : ''}`
    default:
      return `#/explorer${r.owner ? `/${e(r.owner)}` : ''}`
  }
}

export function go(r: Route, replace = false) {
  const h = href(r)
  if (replace) history.replaceState(null, '', h)
  else location.hash = h
  if (replace) window.dispatchEvent(new HashChangeEvent('hashchange'))
}

export const openTable = (owner: string, name: string, tab: TableTab = 'data') =>
  go({ view: 'table', owner, name, tab })

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(location.hash))
  useEffect(() => {
    const on = () => setRoute(parse(location.hash))
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}
