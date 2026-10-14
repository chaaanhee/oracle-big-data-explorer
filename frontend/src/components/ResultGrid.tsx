import { fmtCell } from '../format'
import type { Cell, ColumnKind, Sort } from '../types'

export interface GridColumn {
  name: string
  type?: string
  kind?: ColumnKind
  pk?: boolean
  fk?: boolean
  nullable?: boolean
  comment?: string | null
  sortable?: boolean
}

const NUMERIC = /^(NUMBER|INTEGER|BIGINT|SMALLINT|TINYINT|HUGEINT|DOUBLE|FLOAT|REAL|DECIMAL|BINARY_)/i

interface Props {
  columns: GridColumn[]
  rows: Cell[][]
  rowOffset?: number
  sort?: Sort | null
  onSort?: (column: string) => void
  selected?: number | null
  onRowClick?: (index: number) => void
  loading?: boolean
  empty?: string
}

export default function ResultGrid({ columns, rows, rowOffset = 0, sort, onSort, selected, onRowClick, loading, empty }: Props) {
  const numeric = columns.map((c) => c.kind === 'number' || (c.kind === undefined && NUMERIC.test(c.type ?? '')))

  return (
    <div className={`grid-wrap ${loading ? 'loading' : ''}`}>
      <table className="grid">
        <thead>
          <tr>
            <th className="rownum">#</th>
            {columns.map((c, i) => {
              const sortable = onSort && c.sortable !== false
              const dir = sort?.column === c.name ? sort.direction : null
              return (
                <th
                  key={c.name + i}
                  className={`${sortable ? 'sortable' : ''} ${numeric[i] ? 'num' : ''}`}
                  onClick={sortable ? () => onSort(c.name) : undefined}
                  title={[c.name, c.type, c.comment, c.nullable === false ? 'NOT NULL' : null].filter(Boolean).join('\n')}
                >
                  <div className="th-name">
                    {c.pk && <span className="key pk" title="기본키">PK</span>}
                    {c.fk && <span className="key fk" title="외래키">FK</span>}
                    <span>{c.name}</span>
                    {dir && <span className="sort-ind">{dir === 'asc' ? '▲' : '▼'}</span>}
                  </div>
                  {c.type && (
                    <div className="th-type">
                      {c.type}
                      {c.nullable === false && <span className="nn"> · NOT NULL</span>}
                    </div>
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr>
              <td className="no-rows" colSpan={columns.length + 1}>{loading ? '불러오는 중…' : (empty ?? '행이 없습니다.')}</td>
            </tr>
          )}
          {rows.map((r, ri) => (
            <tr
              key={ri}
              className={`${onRowClick ? 'clickable' : ''} ${selected === ri ? 'selected' : ''}`}
              onClick={onRowClick ? () => onRowClick(ri) : undefined}
            >
              <td className="rownum">{rowOffset + ri + 1}</td>
              {r.map((v, ci) => (
                <td key={ci} className={v === null ? 'null' : numeric[ci] ? 'num' : ''} title={v === null ? undefined : String(v)}>
                  {fmtCell(v)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
