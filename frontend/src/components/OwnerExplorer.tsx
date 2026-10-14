import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { go, openTable } from '../nav'
import { useFavorites } from '../storage'
import { useDebounce } from '../useDebounce'
import { daysAgo, errorText, fmtInt } from '../format'
import type { DbObject } from '../types'

type SortKey = 'name' | 'rows' | 'analyzed'

export default function OwnerExplorer({ owner }: { owner?: string }) {
  const [includeSystem, setIncludeSystem] = useState(false)
  const [ownerFilter, setOwnerFilter] = useState('')
  const owners = useQuery({ queryKey: ['owners', includeSystem], queryFn: () => api.owners(includeSystem) })

  const shownOwners = useMemo(() => {
    const f = ownerFilter.trim().toUpperCase()
    return (owners.data ?? []).filter((o) => !f || o.owner.includes(f))
  }, [owners.data, ownerFilter])

  const totals = useMemo(
    () =>
      (owners.data ?? []).reduce(
        (a, o) => ({ tables: a.tables + o.tables, views: a.views + o.views, indexes: a.indexes + o.indexes }),
        { tables: 0, views: 0, indexes: 0 },
      ),
    [owners.data],
  )

  return (
    <div className="split">
      <section className="pane owner-pane">
        <div className="pane-head">
          <h2>Owner <span className="muted">{owners.data?.length ?? ''}</span></h2>
          <label className="check">
            <input type="checkbox" checked={includeSystem} onChange={(e) => setIncludeSystem(e.target.checked)} />
            시스템
          </label>
        </div>
        <input placeholder="Owner 이름 검색" value={ownerFilter} onChange={(e) => setOwnerFilter(e.target.value)} />
        {owners.error && <div className="notice err">{errorText(owners.error)}</div>}
        <ul className="owner-list">
          <li className={!owner ? 'active' : ''} onClick={() => go({ view: 'explorer' })}>
            <div className="owner-name">전체 개요</div>
            <div className="owner-counts">
              <span>테이블 {fmtInt(totals.tables)}</span>
              <span>뷰 {fmtInt(totals.views)}</span>
              <span>인덱스 {fmtInt(totals.indexes)}</span>
            </div>
          </li>
          {shownOwners.map((o) => (
            <li key={o.owner} className={owner === o.owner ? 'active' : ''} onClick={() => go({ view: 'explorer', owner: o.owner })}>
              <div className="owner-name">
                {o.owner}
                {o.system && <span className="badge sm">SYSTEM</span>}
              </div>
              <div className="owner-counts">
                <span>테이블 {fmtInt(o.tables)}</span>
                <span>뷰 {fmtInt(o.views)}</span>
                <span>인덱스 {fmtInt(o.indexes)}</span>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="pane grow-pane">
        {owner ? <OwnerObjects owner={owner} /> : <Overview />}
      </section>
    </div>
  )
}

function Overview() {
  const owners = useQuery({ queryKey: ['owners', false], queryFn: () => api.owners(false) })
  const refs = useQuery({ queryKey: ['owner-references'], queryFn: api.ownerReferences })
  const [text, setText] = useState('')
  const q = useDebounce(text.trim(), 300)
  const found = useQuery({
    queryKey: ['search', q, 'table', null],
    queryFn: () => api.search(q, ['table'], null),
    enabled: q.length > 0,
  })
  const max = Math.max(1, ...(owners.data ?? []).map((o) => o.tables + o.views))

  return (
    <div className="scroll">
      <div className="pane-head">
        <h2>전체 Owner 개요</h2>
      </div>
      <div className="search">
        <span className="search-icon">⌕</span>
        <input placeholder="모든 Owner 에서 테이블 이름 검색" value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      {q && (
        <div className="card-list">
          {found.isFetching && <div className="muted">검색 중…</div>}
          {found.error && <div className="notice err">{errorText(found.error)}</div>}
          {found.data?.tables?.length === 0 && <div className="muted">일치하는 테이블이 없습니다.</div>}
          {found.data?.tables?.map((t) => (
            <div key={`${t.owner}.${t.name}`} className="hit" onClick={() => openTable(t.owner, t.name)}>
              <span className={`type-tag ${t.type === 'VIEW' ? 'view' : ''}`}>{t.type === 'VIEW' ? 'V' : 'T'}</span>
              <span className="muted">{t.owner}.</span>
              <strong>{t.name}</strong>
              <span className="muted truncate-wide">{t.comment}</span>
            </div>
          ))}
        </div>
      )}

      <h3 className="section-title">Owner 별 객체 수</h3>
      <table className="grid compact">
        <thead>
          <tr>
            <th>Owner</th>
            <th className="num">테이블</th>
            <th className="num">뷰</th>
            <th className="num">인덱스</th>
            <th style={{ width: '40%' }}></th>
          </tr>
        </thead>
        <tbody>
          {owners.data?.map((o) => (
            <tr key={o.owner} className="clickable" onClick={() => go({ view: 'explorer', owner: o.owner })}>
              <td><strong>{o.owner}</strong></td>
              <td className="num">{fmtInt(o.tables)}</td>
              <td className="num">{fmtInt(o.views)}</td>
              <td className="num">{fmtInt(o.indexes)}</td>
              <td>
                <div className="hbar">
                  <div style={{ width: `${(o.tables / max) * 100}%` }} className="hbar-t" />
                  <div style={{ width: `${(o.views / max) * 100}%` }} className="hbar-v" />
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 className="section-title">Owner 간 참조 (FK)</h3>
      {refs.data?.length === 0 && <div className="muted">Owner 를 넘나드는 외래키가 없습니다.</div>}
      <div className="ref-list">
        {refs.data?.map((r) => (
          <div key={`${r.from_owner}>${r.to_owner}`} className="ref-item">
            <div>
              <strong>{r.from_owner}</strong> <span className="arrow">→</span> <strong>{r.to_owner}</strong>
              <span className="badge sm">{r.fk_count} FK</span>
            </div>
            <div className="muted small">{r.examples.join(' · ')}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function OwnerObjects({ owner }: { owner: string }) {
  const objects = useQuery({ queryKey: ['objects', owner], queryFn: () => api.objects(owner) })
  const { isFavorite, toggleFavorite } = useFavorites()
  const [text, setText] = useState('')
  const [type, setType] = useState<'ALL' | 'TABLE' | 'VIEW'>('ALL')
  const [sort, setSort] = useState<SortKey>('name')

  const rows = useMemo(() => {
    const f = text.trim().toUpperCase()
    const list = (objects.data ?? []).filter(
      (o) =>
        (type === 'ALL' || o.type === type) &&
        (!f || o.name.includes(f) || (o.comment ?? '').toUpperCase().includes(f)),
    )
    const cmp: Record<SortKey, (a: DbObject, b: DbObject) => number> = {
      name: (a, b) => a.name.localeCompare(b.name),
      rows: (a, b) => (b.num_rows ?? -1) - (a.num_rows ?? -1),
      analyzed: (a, b) => (a.last_analyzed ?? '').localeCompare(b.last_analyzed ?? ''),
    }
    return [...list].sort(cmp[sort])
  }, [objects.data, text, type, sort])

  return (
    <>
      <div className="pane-head">
        <h2>{owner}</h2>
        <span className="muted">
          테이블 {objects.data?.filter((o) => o.type === 'TABLE').length ?? '-'} · 뷰{' '}
          {objects.data?.filter((o) => o.type === 'VIEW').length ?? '-'}
        </span>
        <span className="spacer" />
        <button className="btn sm" onClick={() => go({ view: 'map', owner })}>ERD 보기</button>
      </div>
      <div className="toolbar">
        <div className="search">
          <span className="search-icon">⌕</span>
          <input placeholder="테이블 이름 또는 설명 검색" value={text} onChange={(e) => setText(e.target.value)} autoFocus />
        </div>
        <div className="seg">
          {(['ALL', 'TABLE', 'VIEW'] as const).map((t) => (
            <button key={t} className={type === t ? 'active' : ''} onClick={() => setType(t)}>
              {t === 'ALL' ? '전체' : t === 'TABLE' ? '테이블' : '뷰'}
            </button>
          ))}
        </div>
        <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
          <option value="name">이름순</option>
          <option value="rows">행 수 많은 순</option>
          <option value="analyzed">통계 오래된 순</option>
        </select>
      </div>
      {objects.error && <div className="notice err">{errorText(objects.error)}</div>}
      <div className="grid-wrap">
        <table className="grid">
          <thead>
            <tr>
              <th style={{ width: 32 }}></th>
              <th>이름</th>
              <th>설명</th>
              <th className="num" title="옵티마이저 통계의 NUM_ROWS (추정치)">행 수 (통계)</th>
              <th className="num">컬럼</th>
              <th className="num">인덱스</th>
              <th>통계 수집</th>
              <th>최근 DDL</th>
            </tr>
          </thead>
          <tbody>
            {objects.isLoading && (
              <tr><td colSpan={8} className="no-rows">불러오는 중…</td></tr>
            )}
            {objects.data && rows.length === 0 && (
              <tr><td colSpan={8} className="no-rows">조건에 맞는 객체가 없습니다.</td></tr>
            )}
            {rows.map((o) => (
              <tr key={o.name} className="clickable" onClick={() => openTable(owner, o.name)}>
                <td>
                  <button
                    className={`icon-btn star ${isFavorite(o) ? 'on' : ''}`}
                    onClick={(e) => {
                      e.stopPropagation()
                      toggleFavorite(o)
                    }}
                  >
                    {isFavorite(o) ? '★' : '☆'}
                  </button>
                </td>
                <td>
                  <span className={`type-tag ${o.type === 'VIEW' ? 'view' : ''}`}>{o.type === 'VIEW' ? 'V' : 'T'}</span>
                  <strong>{o.name}</strong>
                  {o.status !== 'VALID' && <span className="badge sm badge-bad">{o.status}</span>}
                </td>
                <td className="muted truncate-wide">{o.comment}</td>
                <td className="num">{o.type === 'VIEW' ? '' : fmtInt(o.num_rows)}</td>
                <td className="num">{o.columns}</td>
                <td className="num">{o.type === 'VIEW' ? '' : o.indexes}</td>
                <td className={staleClass(o)}>
                  {o.type === 'VIEW' ? '' : o.last_analyzed ? daysAgo(o.last_analyzed) : '수집 안 됨'}
                </td>
                <td className="muted">{daysAgo(o.last_ddl_time)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  )
}

function staleClass(o: DbObject) {
  if (o.type === 'VIEW') return ''
  if (!o.last_analyzed) return 'bad-text'
  const days = (Date.now() - new Date(o.last_analyzed.replace(' ', 'T')).getTime()) / 86_400_000
  return days > 30 ? 'warn-text' : 'muted'
}
