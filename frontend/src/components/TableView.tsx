import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../api'
import { go, type Route, type TableTab } from '../nav'
import { useFavorites, useRecent } from '../storage'
import { errorText } from '../format'
import type { Info } from '../types'
import DataViewer from './DataViewer'
import StructurePanel from './StructurePanel'
import Profiler from './Profiler'
import RelationsPanel from './RelationsPanel'

const TABS: { id: TableTab; label: string }[] = [
  { id: 'data', label: '데이터' },
  { id: 'structure', label: '구조' },
  { id: 'profile', label: '프로파일' },
  { id: 'relations', label: '관계' },
]

type TableRoute = Extract<Route, { view: 'table' }>

export default function TableView({ route, info }: { route: TableRoute; info?: Info }) {
  const { owner, name, tab } = route
  const detail = useQuery({ queryKey: ['table', owner, name], queryFn: () => api.table(owner, name) })
  const { isFavorite, toggleFavorite } = useFavorites()
  const { touch } = useRecent()

  useEffect(() => {
    if (detail.data) touch({ owner, name })
  }, [detail.data, owner, name, touch])

  const ref = { owner, name }

  return (
    <div className="table-view">
      <header className="topbar">
        <div className="topbar-title">
          <button className="crumb" onClick={() => go({ view: 'explorer', owner })}>{owner}</button>
          <span className="muted">/</span>
          {detail.data && (
            <span className={`type-tag ${detail.data.type === 'VIEW' ? 'view' : ''}`}>
              {detail.data.type === 'VIEW' ? 'V' : 'T'}
            </span>
          )}
          <h1>{name}</h1>
          <button
            className={`icon-btn star big ${isFavorite(ref) ? 'on' : ''}`}
            title={isFavorite(ref) ? '즐겨찾기 해제' : '즐겨찾기 추가'}
            onClick={() => toggleFavorite(ref)}
          >
            {isFavorite(ref) ? '★' : '☆'}
          </button>
          {detail.data?.comment && <span className="muted truncate-wide">{detail.data.comment}</span>}
        </div>
        <div className="tabs">
          {TABS.map((t) => (
            <button
              key={t.id}
              className={`tab ${tab === t.id ? 'active' : ''}`}
              onClick={() => go({ view: 'table', owner, name, tab: t.id }, true)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </header>

      <div className="content">
        {detail.error && <div className="notice err">{errorText(detail.error)}</div>}
        {detail.isLoading && <div className="muted">테이블 정보를 읽는 중…</div>}
        {detail.data && (
          <>
            <div className={`tab-keep ${tab === 'data' ? '' : 'hidden'}`}>
              <DataViewer detail={detail.data} info={info} />
            </div>
            {tab === 'structure' && <StructurePanel detail={detail.data} />}
            {tab === 'profile' && <Profiler detail={detail.data} info={info} />}
            {tab === 'relations' && <RelationsPanel detail={detail.data} />}
          </>
        )}
      </div>
    </div>
  )
}
