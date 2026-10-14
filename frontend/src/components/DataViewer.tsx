import { useMemo, useState } from 'react'
import { keepPreviousData, useMutation, useQuery } from '@tanstack/react-query'
import { api, download } from '../api'
import { go } from '../nav'
import { useStored } from '../storage'
import { useDebounce } from '../useDebounce'
import { errorText, fmtCell, fmtInt, fmtMs } from '../format'
import type { Column, Filter, FilterOp, Info, RowQuery, Sort, TableDetail } from '../types'
import ResultGrid from './ResultGrid'

const OP_LABEL: Record<FilterOp, string> = {
  eq: '=', neq: '≠', gt: '>', gte: '≥', lt: '<', lte: '≤',
  contains: '포함', not_contains: '미포함', starts_with: '시작', ends_with: '끝',
  in: 'IN (쉼표 구분)', between: '범위', is_null: 'NULL', not_null: 'NOT NULL',
}

function opsFor(c: Column | undefined): FilterOp[] {
  if (!c) return []
  if (c.kind === 'lob' || c.kind === 'opaque') return ['is_null', 'not_null']
  if (c.kind === 'text')
    return ['contains', 'eq', 'neq', 'starts_with', 'ends_with', 'not_contains', 'in', 'gt', 'lt', 'is_null', 'not_null']
  return ['eq', 'neq', 'gt', 'gte', 'lt', 'lte', 'between', 'in', 'is_null', 'not_null']
}

const needsValue = (op: FilterOp) => op !== 'is_null' && op !== 'not_null'
const complete = (f: Filter) =>
  !needsValue(f.op) || (!!f.value?.trim() && (f.op !== 'between' || !!f.value2?.trim()))

export default function DataViewer({ detail, info }: { detail: TableDetail; info?: Info }) {
  const { owner, name, columns } = detail
  const [search, setSearch] = useState('')
  const [filters, setFilters] = useState<Filter[]>([])
  const [sort, setSort] = useState<Sort | null>(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(100)
  const [selected, setSelected] = useState<number | null>(null)
  const [, setDraft] = useStored<string>('sql-draft', '')

  const debouncedSearch = useDebounce(search.trim(), 400)
  const debouncedFilters = useDebounce(filters, 400)
  const query: RowQuery = useMemo(
    () => ({ search: debouncedSearch || undefined, filters: debouncedFilters.filter(complete), sort }),
    [debouncedSearch, debouncedFilters, sort],
  )
  const queryKey = JSON.stringify(query)

  const objects = useQuery({ queryKey: ['objects', owner], queryFn: () => api.objects(owner) })
  const estimate = objects.data?.find((o) => o.name === name)?.num_rows ?? null

  const rows = useQuery({
    queryKey: ['rows', owner, name, queryKey, page, pageSize],
    queryFn: () => api.rows(owner, name, query, page, pageSize),
    placeholderData: keepPreviousData,
  })
  const count = useMutation({ mutationFn: () => api.count(owner, name, query) })
  const [countKey, setCountKey] = useState('')

  const resetPage = () => {
    setPage(1)
    setSelected(null)
  }

  const toggleSort = (column: string) => {
    resetPage()
    setSort((s) =>
      s?.column !== column ? { column, direction: 'asc' } : s.direction === 'asc' ? { column, direction: 'desc' } : null,
    )
  }

  const updateFilter = (i: number, patch: Partial<Filter>) => {
    resetPage()
    setFilters((fs) => fs.map((f, j) => (j === i ? { ...f, ...patch } : f)))
  }

  const gridColumns = columns.map((c) => ({
    name: c.name, type: c.type, kind: c.kind, pk: c.pk, fk: (c.fk?.length ?? 0) > 0,
    nullable: c.nullable, comment: c.comment, sortable: c.kind !== 'lob' && c.kind !== 'opaque',
  }))

  const data = rows.data
  const pageRows = data?.rows ?? []
  const record = selected !== null ? pageRows[selected] : null
  const maxPage = info?.limits.page_max_rows ?? 500
  const activeFilters = query.filters.length + (query.search ? 1 : 0)

  return (
    <div className="explore">
      <div className="toolbar">
        <div className="search">
          <span className="search-icon">⌕</span>
          <input
            placeholder="문자 컬럼 포함 검색 · 숫자는 일치 검색"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value)
              resetPage()
            }}
          />
          {search && <button className="icon-btn" onClick={() => setSearch('')}>✕</button>}
        </div>
        <button
          className="btn"
          onClick={() => {
            const first = columns.find((c) => c.kind !== 'lob' && c.kind !== 'opaque') ?? columns[0]
            setFilters((fs) => [...fs, { column: first.name, op: opsFor(first)[0] }])
          }}
        >
          + 필터
        </button>
        <button
          className="btn"
          title="현재 검색·필터·정렬 조건의 결과를 CSV 로 내려받습니다 (서버에서 스트리밍)"
          onClick={() => download(api.exportUrl(owner, name, query))}
        >
          CSV 내보내기
        </button>
        <button
          className="btn ghost"
          onClick={() => {
            setDraft(() => `SELECT *\nFROM ${owner}.${name}\nFETCH FIRST 100 ROWS ONLY`)
            go({ view: 'sql' })
          }}
        >
          SQL 로 열기
        </button>
      </div>

      {filters.length > 0 && (
        <div className="filters">
          {filters.map((f, i) => {
            const col = columns.find((c) => c.name === f.column)
            const ops = opsFor(col)
            return (
              <div key={i} className={`filter-row ${complete(f) ? '' : 'incomplete'}`}>
                <select
                  value={f.column}
                  onChange={(e) => {
                    const c = columns.find((x) => x.name === e.target.value)
                    const nextOps = opsFor(c)
                    updateFilter(i, { column: e.target.value, op: nextOps.includes(f.op) ? f.op : nextOps[0] })
                  }}
                >
                  {columns.map((c) => (
                    <option key={c.name} value={c.name}>{c.name} ({c.type})</option>
                  ))}
                </select>
                <select value={f.op} onChange={(e) => updateFilter(i, { op: e.target.value as FilterOp })}>
                  {ops.map((op) => (
                    <option key={op} value={op}>{OP_LABEL[op]}</option>
                  ))}
                </select>
                {needsValue(f.op) && (
                  <input
                    placeholder={col?.kind === 'date' ? '2024-01-31' : f.op === 'in' ? 'A,B,C' : '값'}
                    value={f.value ?? ''}
                    onChange={(e) => updateFilter(i, { value: e.target.value })}
                  />
                )}
                {f.op === 'between' && (
                  <>
                    <span className="muted">~</span>
                    <input
                      placeholder={col?.kind === 'date' ? '2024-12-31' : '끝 값'}
                      value={f.value2 ?? ''}
                      onChange={(e) => updateFilter(i, { value2: e.target.value })}
                    />
                  </>
                )}
                <button
                  className="icon-btn"
                  onClick={() => {
                    resetPage()
                    setFilters((fs) => fs.filter((_, j) => j !== i))
                  }}
                >
                  ✕
                </button>
              </div>
            )
          })}
        </div>
      )}

      <div className="statusbar">
        <div className="row gap-sm">
          {rows.error ? (
            <span className="bad-text">{errorText(rows.error)}</span>
          ) : (
            <>
              <span>
                {data ? `${fmtInt((page - 1) * pageSize + (pageRows.length ? 1 : 0))}–${fmtInt((page - 1) * pageSize + pageRows.length)}행` : ''}
                {data?.has_more ? ' (다음 페이지 있음)' : data ? ' (마지막)' : ''}
              </span>
              {data && <span className="muted">· {fmtMs(data.elapsed_ms)}</span>}
              {rows.isFetching && <span className="spinner" />}
            </>
          )}
        </div>
        <div className="row gap-sm">
          {activeFilters === 0 && estimate !== null && (
            <span className="muted" title="옵티마이저 통계 NUM_ROWS — 실제와 다를 수 있습니다">
              통계상 약 {fmtInt(estimate)}행
            </span>
          )}
          {countKey === queryKey && count.data ? (
            <span title={`COUNT(*) ${fmtMs(count.data.elapsed_ms)}`}>
              <strong>정확한 건수 {fmtInt(count.data.count)}행</strong>
            </span>
          ) : (
            <button
              className="btn sm"
              disabled={count.isPending}
              title="COUNT(*) 를 실행합니다. 큰 테이블에서는 시간이 걸릴 수 있습니다."
              onClick={() => {
                setCountKey(queryKey)
                count.mutate()
              }}
            >
              {count.isPending ? '세는 중…' : '정확한 건수 세기'}
            </button>
          )}
          {count.error && countKey === queryKey && <span className="bad-text">{errorText(count.error)}</span>}
        </div>
      </div>

      <div className="data-body">
        <ResultGrid
          columns={gridColumns}
          rows={pageRows}
          rowOffset={(page - 1) * pageSize}
          sort={sort}
          onSort={toggleSort}
          selected={selected}
          onRowClick={(i) => setSelected(i === selected ? null : i)}
          loading={rows.isFetching}
          empty={activeFilters ? '조건에 맞는 행이 없습니다.' : '테이블이 비어 있습니다.'}
        />
        {record && (
          <aside className="record">
            <div className="row">
              <strong>행 {(page - 1) * pageSize + (selected ?? 0) + 1}</strong>
              <span className="spacer" />
              <button className="icon-btn" onClick={() => setSelected(null)}>✕</button>
            </div>
            <dl>
              {columns.map((c, i) => (
                <div key={c.name}>
                  <dt>
                    {c.pk && <span className="key pk">PK</span>}
                    {c.name} <span className="muted">{c.type}</span>
                  </dt>
                  <dd className={record[i] === null ? 'null' : ''}>{fmtCell(record[i])}</dd>
                </div>
              ))}
            </dl>
          </aside>
        )}
      </div>

      <div className="pager">
        <div className="row gap-sm">
          <span className="muted">페이지 크기</span>
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value))
              resetPage()
            }}
          >
            {[50, 100, 200, 500, 1000].filter((n) => n <= maxPage).map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
          <span className="muted small">한 번에 이 행 수만 DB 에서 가져옵니다</span>
        </div>
        <div className="page-info">
          <button className="btn sm" disabled={page <= 1} onClick={() => { setPage(1); setSelected(null) }}>«</button>
          <button className="btn sm" disabled={page <= 1} onClick={() => { setPage((p) => p - 1); setSelected(null) }}>‹ 이전</button>
          <span>
            <input
              type="number"
              min={1}
              value={page}
              onChange={(e) => {
                const n = Math.max(1, Number(e.target.value) || 1)
                setPage(n)
                setSelected(null)
              }}
            />{' '}
            페이지
          </span>
          <button className="btn sm" disabled={!data?.has_more} onClick={() => { setPage((p) => p + 1); setSelected(null) }}>다음 ›</button>
        </div>
      </div>
    </div>
  )
}
