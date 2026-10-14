import type {
  DbObject, Distribution, ErdGraph, Info, Owner, OwnerReference, ProfileMetadata, Related, RowQuery,
  RowsResponse, ScanProfile, SearchResult, SqlResult, TableDetail,
} from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: init?.body ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!res.ok) {
    let message = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((d: { msg: string }) => d.msg).join(', ')
    } catch { /* 본문이 JSON 이 아니면 상태 코드만 보여 준다 */ }
    throw new ApiError(res.status, message)
  }
  return res.json()
}

const post = <T>(path: string, body?: unknown) =>
  request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) })

const t = (owner: string, table: string) => `/api/tables/${encodeURIComponent(owner)}/${encodeURIComponent(table)}`
const o = (owner: string) => `/api/owners/${encodeURIComponent(owner)}`

export const api = {
  info: () => request<Info>('/api/info'),
  clearCache: () => post<{ ok: boolean }>('/api/cache/clear'),

  owners: (includeSystem: boolean) => request<Owner[]>(`/api/owners?include_system=${includeSystem}`),
  objects: (owner: string) => request<DbObject[]>(`${o(owner)}/objects`),
  ownerReferences: () => request<OwnerReference[]>('/api/owner-references'),

  table: (owner: string, table: string) => request<TableDetail>(t(owner, table)),
  rows: (owner: string, table: string, query: RowQuery, page: number, pageSize: number) =>
    post<RowsResponse>(`${t(owner, table)}/rows`, { ...query, page, page_size: pageSize }),
  count: (owner: string, table: string, query: RowQuery) =>
    post<{ count: number; elapsed_ms: number }>(`${t(owner, table)}/count`, query),
  exportUrl: (owner: string, table: string, query: RowQuery) =>
    `${t(owner, table)}/export?q=${encodeURIComponent(JSON.stringify(query))}`,

  sql: (sql: string, maxRows: number) => post<SqlResult>('/api/sql', { sql, max_rows: maxRows }),
  sqlExportUrl: (sql: string) => `/api/sql/export?sql=${encodeURIComponent(sql)}`,

  profileMetadata: (owner: string, table: string) => request<ProfileMetadata>(`${t(owner, table)}/profile/metadata`),
  profileScan: (owner: string, table: string, mode: 'sample' | 'exact') =>
    post<ScanProfile>(`${t(owner, table)}/profile/${mode}`),
  distribution: (owner: string, table: string, column: string, source: 'stats' | 'sample') =>
    request<Distribution>(`${t(owner, table)}/distribution?column=${encodeURIComponent(column)}&source=${source}`),

  erd: (owner: string, relatedOnly: boolean, limit: number) =>
    request<ErdGraph>(`${o(owner)}/erd?related_only=${relatedOnly}&limit=${limit}`),
  neighborhood: (owner: string, table: string, depth: number) =>
    request<ErdGraph>(`${t(owner, table)}/neighborhood?depth=${depth}`),

  search: (q: string, kinds: string[], owner: string | null) =>
    request<SearchResult>(
      `/api/search?q=${encodeURIComponent(q)}&kinds=${kinds.join(',')}${owner ? `&owner=${encodeURIComponent(owner)}` : ''}`,
    ),
  related: (owner: string, table: string) => request<Related>(`${t(owner, table)}/related`),
}

/** 수십만 행 CSV 를 브라우저 메모리에 올리지 않도록 서버 스트림을 브라우저 다운로드로 바로 받는다. */
export function download(url: string) {
  const a = document.createElement('a')
  a.href = url
  a.download = ''
  document.body.appendChild(a)
  a.click()
  a.remove()
}
