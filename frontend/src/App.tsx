import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { go, href, openTable, useRoute, type Route } from './nav'
import { useFavorites, useRecent } from './storage'
import { daysAgo } from './format'
import OwnerExplorer from './components/OwnerExplorer'
import TableView from './components/TableView'
import SqlWorkbench from './components/SqlWorkbench'
import SchemaMap from './components/SchemaMap'
import GlobalSearch from './components/GlobalSearch'

const NAV: { view: Route['view']; label: string; icon: string; to: Route }[] = [
  { view: 'explorer', label: '스키마 탐색기', icon: '▤', to: { view: 'explorer' } },
  { view: 'sql', label: 'SQL 워크벤치', icon: '⌘', to: { view: 'sql' } },
  { view: 'map', label: '스키마 맵 (ERD)', icon: '⬡', to: { view: 'map' } },
  { view: 'search', label: '전체 검색', icon: '⌕', to: { view: 'search' } },
]

export default function App() {
  const route = useRoute()
  const info = useQuery({ queryKey: ['info'], queryFn: api.info, staleTime: Infinity })
  const { favorites, toggleFavorite } = useFavorites()
  const { recent, clear } = useRecent()
  const [quick, setQuick] = useState('')
  const qc = useQueryClient()

  const refresh = async () => {
    await api.clearCache()
    await qc.invalidateQueries()
  }

  const active = route.view === 'table' ? 'explorer' : route.view
  const current = route.view === 'table' ? `${route.owner}.${route.name}` : null

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">◈</div>
          <div>
            <strong>Big Data Explorer</strong>
            <small>Oracle 스키마 탐색</small>
          </div>
        </div>

        <div className="side-section conn">
          {info.isLoading && <div className="muted">연결 확인 중…</div>}
          {info.error && <div className="notice err">백엔드에 연결할 수 없습니다</div>}
          {info.data && (
            <>
              <div className="row gap-sm">
                <span className={`badge ${info.data.mode === 'demo' ? 'badge-demo' : 'badge-oracle'}`}>
                  {info.data.mode === 'demo' ? 'DEMO' : 'ORACLE'}
                </span>
                <strong className="truncate">{info.data.user}</strong>
                <span className="spacer" />
                <button className="icon-btn" title="메타데이터 캐시 비우고 새로 읽기" onClick={refresh}>⟳</button>
              </div>
              <div className="conn-ver" title={info.data.dsn}>{info.data.version}</div>
              <div className="row gap-sm" style={{ marginTop: 6 }}>
                {info.data.account.read_only ? (
                  <span className="badge badge-ok" title="쓰기 권한·소유 객체가 발견되지 않았습니다">읽기 전용 계정</span>
                ) : (
                  <span className="badge badge-bad" title={info.data.account.findings.map((f) => f.text).join('\n')}>
                    쓰기 권한 감지
                  </span>
                )}
                <span className="badge" title="SQL 실행 제한">
                  {info.data.limits.query_timeout_sec}s · {info.data.limits.sql_max_rows.toLocaleString()}행
                </span>
              </div>
            </>
          )}
        </div>

        <form
          className="side-section"
          onSubmit={(e) => {
            e.preventDefault()
            if (quick.trim()) go({ view: 'search', q: quick.trim() })
          }}
        >
          <input
            className="block-input"
            placeholder="테이블·컬럼·주석 검색 (Enter)"
            value={quick}
            onChange={(e) => setQuick(e.target.value)}
          />
        </form>

        <nav className="side-nav">
          {NAV.map((n) => (
            <a key={n.view} href={href(n.to)} className={active === n.view ? 'active' : ''}>
              <span className="nav-icon">{n.icon}</span>
              {n.label}
            </a>
          ))}
        </nav>

        <div className="side-section grow">
          <h3>즐겨찾기 <span className="muted">{favorites.length || ''}</span></h3>
          {favorites.length === 0 && <div className="hint">테이블 옆 ☆ 를 눌러 추가하세요.</div>}
          <ul className="side-list">
            {favorites.map((f) => (
              <li
                key={`${f.owner}.${f.name}`}
                className={current === `${f.owner}.${f.name}` ? 'active' : ''}
                onClick={() => openTable(f.owner, f.name)}
              >
                <span className="side-owner">{f.owner}.</span>
                <span className="side-name">{f.name}</span>
                <button
                  className="icon-btn star on"
                  title="즐겨찾기 해제"
                  onClick={(e) => {
                    e.stopPropagation()
                    toggleFavorite(f)
                  }}
                >
                  ★
                </button>
              </li>
            ))}
          </ul>

          <h3 className="row" style={{ marginTop: 18 }}>
            최근 조회
            <span className="spacer" />
            {recent.length > 0 && <button className="icon-btn" onClick={clear}>비우기</button>}
          </h3>
          {recent.length === 0 && <div className="hint">조회한 테이블이 여기에 쌓입니다.</div>}
          <ul className="side-list">
            {recent.map((r) => (
              <li
                key={`${r.owner}.${r.name}`}
                className={current === `${r.owner}.${r.name}` ? 'active' : ''}
                onClick={() => openTable(r.owner, r.name)}
                title={new Date(r.at).toLocaleString()}
              >
                <span className="side-owner">{r.owner}.</span>
                <span className="side-name">{r.name}</span>
                <small className="muted side-time">{daysAgo(new Date(r.at).toISOString())}</small>
              </li>
            ))}
          </ul>
        </div>
      </aside>

      <main className="main">
        {route.view === 'explorer' && <OwnerExplorer owner={route.owner} />}
        {route.view === 'table' && <TableView key={`${route.owner}.${route.name}`} route={route} info={info.data} />}
        {route.view === 'sql' && <SqlWorkbench info={info.data} />}
        {route.view === 'map' && <SchemaMap owner={route.owner} focus={route.focus} />}
        {route.view === 'search' && <GlobalSearch q={route.q} />}
      </main>
    </div>
  )
}
