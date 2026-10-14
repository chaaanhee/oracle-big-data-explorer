import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { go, openTable } from '../nav'
import { useDebounce } from '../useDebounce'
import { errorText, fmtMs } from '../format'

const KINDS = [
  { id: 'table', label: '테이블 이름' },
  { id: 'column', label: '컬럼 이름' },
  { id: 'comment', label: '테이블·컬럼 주석' },
  { id: 'similar', label: '비슷한 이름' },
] as const

function Hl({ text, q }: { text: string | null; q: string }) {
  if (!text) return null
  const i = text.toUpperCase().indexOf(q.toUpperCase())
  if (!q || i < 0) return <>{text}</>
  return (
    <>
      {text.slice(0, i)}
      <mark>{text.slice(i, i + q.length)}</mark>
      {text.slice(i + q.length)}
    </>
  )
}

export default function GlobalSearch({ q: initial }: { q?: string }) {
  const [text, setText] = useState(initial ?? '')
  const [kinds, setKinds] = useState<string[]>(KINDS.map((k) => k.id))
  const [owner, setOwner] = useState('')
  const owners = useQuery({ queryKey: ['owners', false], queryFn: () => api.owners(false) })
  const q = useDebounce(text.trim(), 300)

  const pushed = useRef(initial ?? '')

  useEffect(() => {
    if ((initial ?? '') !== pushed.current) {
      pushed.current = initial ?? ''
      setText(initial ?? '')
    }
  }, [initial])
  useEffect(() => {
    if (q !== pushed.current) {
      pushed.current = q
      go({ view: 'search', q: q || undefined }, true)
    }
  }, [q])

  const res = useQuery({
    queryKey: ['search', q, kinds.join(','), owner],
    queryFn: () => api.search(q, kinds, owner || null),
    enabled: q.length > 0 && kinds.length > 0,
  })
  const d = res.data

  return (
    <div className="search-view">
      <header className="topbar">
        <div className="topbar-title">
          <h1>전체 검색</h1>
          <span className="muted">모든 Owner 의 테이블·컬럼·주석을 검색합니다</span>
        </div>
      </header>
      <div className="content scroll">
        <div className="toolbar">
          <div className="search big">
            <span className="search-icon">⌕</span>
            <input
              autoFocus
              placeholder="예: CUSTOMER, ORDER_ID, 고객, 주문"
              value={text}
              onChange={(e) => setText(e.target.value)}
            />
          </div>
          <select value={owner} onChange={(e) => setOwner(e.target.value)}>
            <option value="">모든 Owner</option>
            {owners.data?.map((o) => (
              <option key={o.owner} value={o.owner}>{o.owner}</option>
            ))}
          </select>
        </div>
        <div className="row gap-sm wrap">
          {KINDS.map((k) => (
            <label key={k.id} className="check chip-check">
              <input
                type="checkbox"
                checked={kinds.includes(k.id)}
                onChange={(e) => setKinds((ks) => (e.target.checked ? [...ks, k.id] : ks.filter((x) => x !== k.id)))}
              />
              {k.label}
            </label>
          ))}
          {d && <span className="muted small">· {fmtMs(d.elapsed_ms)}</span>}
          {res.isFetching && <span className="spinner" />}
        </div>
        {res.error && <div className="notice err">{errorText(res.error)}</div>}
        {!q && <div className="empty small"><h2>검색어를 입력하세요</h2><p>테이블 이름, 컬럼 이름, 주석(설명)을 한 번에 찾습니다.</p></div>}

        {d && (
          <div className="search-results">
            {d.tables && (
              <section>
                <h3>테이블 · 뷰 <span className="muted">{d.tables.length}</span></h3>
                {d.tables.length === 0 && <div className="muted small">없음</div>}
                {d.tables.map((t) => (
                  <div key={`${t.owner}.${t.name}`} className="hit">
                    <span className={`type-tag ${t.type === 'VIEW' ? 'view' : ''}`}>{t.type === 'VIEW' ? 'V' : 'T'}</span>
                    <span className="muted">{t.owner}.</span>
                    <button className="link strong" onClick={() => openTable(t.owner, t.name)}><Hl text={t.name} q={q} /></button>
                    <span className="muted truncate-wide">{t.comment}</span>
                    <span className="spacer" />
                    <button className="btn sm ghost" onClick={() => openTable(t.owner, t.name, 'relations')}>관련 테이블</button>
                  </div>
                ))}
              </section>
            )}

            {d.columns && (
              <section>
                <h3>컬럼 <span className="muted">{d.columns.length}</span></h3>
                {d.columns.length === 0 && <div className="muted small">없음</div>}
                {d.columns.map((c) => (
                  <div key={`${c.owner}.${c.table}.${c.column}`} className="hit" onClick={() => openTable(c.owner, c.table, 'structure')}>
                    <span className="muted">{c.owner}.{c.table}.</span>
                    <strong><Hl text={c.column} q={q} /></strong>
                    <span className="mono small muted">{c.type}</span>
                    <span className="muted truncate-wide">{c.comment}</span>
                  </div>
                ))}
              </section>
            )}

            {d.comments && (
              <section>
                <h3>주석 <span className="muted">{d.comments.length}</span></h3>
                {d.comments.length === 0 && <div className="muted small">없음</div>}
                {d.comments.map((c, i) => (
                  <div key={i} className="hit" onClick={() => openTable(c.owner, c.table, c.column ? 'structure' : 'data')}>
                    <span className="badge sm">{c.column ? '컬럼' : '테이블'}</span>
                    <span className="muted">{c.owner}.</span>
                    <strong>{c.table}{c.column ? `.${c.column}` : ''}</strong>
                    <span><Hl text={c.comment} q={q} /></span>
                  </div>
                ))}
              </section>
            )}

            {d.similar && (
              <section>
                <h3>이름이 비슷한 테이블 <span className="muted">{d.similar.length}</span></h3>
                {d.similar.length === 0 && <div className="muted small">없음</div>}
                {d.similar.map((s) => (
                  <div key={`${s.owner}.${s.name}`} className="hit" onClick={() => openTable(s.owner, s.name)}>
                    <span className={`type-tag ${s.type === 'VIEW' ? 'view' : ''}`}>{s.type === 'VIEW' ? 'V' : 'T'}</span>
                    <span className="muted">{s.owner}.</span>
                    <strong>{s.name}</strong>
                    <span className="spacer" />
                    <span className="score">{Math.round(s.score * 100)}%</span>
                  </div>
                ))}
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
