export type Level = 'ok' | 'info' | 'warn' | 'bad'
export type ColumnKind = 'number' | 'date' | 'text' | 'lob' | 'opaque'
export type Cell = string | number | boolean | null

export interface Info {
  mode: 'oracle' | 'demo'
  user: string
  version: string
  dsn: string
  limits: {
    query_timeout_sec: number
    sql_max_rows: number
    export_max_rows: number
    page_max_rows: number
    sql_concurrency: number
    sample_target_rows: number
    exact_profile_timeout_sec: number
  }
  account: { read_only: boolean; findings: { level: Level; text: string }[] }
}

export interface Owner {
  owner: string
  created: string | null
  system: boolean
  tables: number
  views: number
  indexes: number
}

export interface DbObject {
  owner: string
  name: string
  type: 'TABLE' | 'VIEW'
  status: string
  created: string | null
  last_ddl_time: string | null
  num_rows: number | null
  last_analyzed: string | null
  comment: string | null
  indexes: number
  columns: number
}

export interface Column {
  id: number
  name: string
  data_type: string
  type: string
  kind: ColumnKind
  nullable: boolean
  default: string | null
  comment: string | null
  pk?: boolean
  fk?: string[]
}

export interface KeyConstraint {
  name: string
  columns: string[]
  status: string
}

export interface ForeignKey {
  name: string
  from_owner: string
  from_table: string
  from_columns: string[]
  to_owner: string
  to_table: string
  to_columns: string[]
  delete_rule: string | null
  status: string
}

export interface IndexInfo {
  owner: string
  name: string
  type: string
  unique: boolean
  status: string
  columns: string[]
}

export interface TableDetail {
  owner: string
  name: string
  type: 'TABLE' | 'VIEW'
  status: string
  created: string | null
  last_ddl_time: string | null
  comment: string | null
  view_text: string | null
  columns: Column[]
  primary_key: KeyConstraint | null
  unique_keys: KeyConstraint[]
  foreign_keys: ForeignKey[]
  referenced_by: ForeignKey[]
  indexes: IndexInfo[]
}

export type FilterOp =
  | 'eq' | 'neq' | 'gt' | 'gte' | 'lt' | 'lte'
  | 'contains' | 'not_contains' | 'starts_with' | 'ends_with'
  | 'in' | 'between' | 'is_null' | 'not_null'

export interface Filter {
  column: string
  op: FilterOp
  value?: string
  value2?: string
}

export interface Sort {
  column: string
  direction: 'asc' | 'desc'
}

export interface RowQuery {
  search?: string
  filters: Filter[]
  sort: Sort | null
}

export interface RowsResponse {
  columns: Column[]
  rows: Cell[][]
  page: number
  page_size: number
  has_more: boolean
  elapsed_ms: number
}

export interface SqlColumn {
  name: string
  type: string
}

export interface SqlResult {
  columns: SqlColumn[]
  rows: Cell[][]
  row_count: number
  truncated: boolean
  elapsed_ms: number
}

export type ProfileSourceKind = 'metadata' | 'stats' | 'sample' | 'exact'

export interface QualityItem {
  level: Level
  title: string
  detail: string
  source: ProfileSourceKind
}

export interface MetaColumn {
  name: string
  type: string
  data_type: string
  kind: ColumnKind
  nullable: boolean
  comment: string | null
  num_distinct?: number | null
  num_nulls?: number | null
  null_ratio?: number | null
  low?: Cell
  high?: Cell
  density?: number | null
  histogram?: string | null
  num_buckets?: number | null
  sample_size?: number | null
  last_analyzed?: string | null
  avg_col_len?: number | null
}

export interface ProfileMetadata {
  table: {
    type: 'TABLE' | 'VIEW'
    status: string
    created: string | null
    last_ddl_time: string | null
    num_rows: number | null
    blocks: number | null
    avg_row_len: number | null
    sample_size: number | null
    last_analyzed: string | null
    stats_age_days: number | null
    stale_stats: string | null
    stats_locked: boolean
    partitioned: boolean
    compression: string | null
    tablespace: string | null
    size: { bytes: number | null; source: ProfileSourceKind | null; note: string } | null
    modifications: {
      inserts: number | null
      updates: number | null
      deletes: number | null
      truncated: boolean
      timestamp: string | null
    } | null
  }
  columns: MetaColumn[]
  quality: QualityItem[]
  elapsed_ms: number
}

export interface ScanSource {
  mode: 'sample' | 'exact'
  label: string
  percent?: number
  estimated_rows: number | null
}

export interface ScanColumn {
  non_null: number
  nulls: number
  null_ratio: number | null
  distinct?: number | null
  distinct_ratio?: number | null
  min?: Cell
  max?: Cell
}

export interface ScanProfile {
  source: ScanSource
  rows_scanned: number | null
  columns: Record<string, ScanColumn>
  elapsed_ms: number
}

export interface DistBar {
  label: string
  count: number
  ratio?: number
}

export interface Distribution {
  source: 'stats' | 'sample'
  column: string
  kind: 'categorical' | 'histogram' | 'buckets' | 'none'
  histogram?: string | null
  sample?: ScanSource
  values?: DistBar[]
  bins?: DistBar[]
  rows?: number
  nulls?: number
  others?: number
  min?: Cell
  max?: Cell
  note?: string
  reason?: string
  last_analyzed?: string | null
}

export interface ErdColumn {
  name: string
  type: string
  kind: ColumnKind
  nullable: boolean
  comment: string | null
  pk: boolean
  fk: boolean
}

export interface ErdNode {
  id: string
  owner: string
  name: string
  type: 'TABLE' | 'VIEW'
  comment: string | null
  num_rows: number | null
  external: boolean
  column_count: number
  columns: ErdColumn[]
  depth?: number
}

export interface ErdEdge {
  id: string
  name: string
  source: string
  target: string
  from_columns: string[]
  to_columns: string[]
  cross_owner: boolean
}

export interface ErdGraph {
  nodes: ErdNode[]
  edges: ErdEdge[]
  truncated: boolean
  owner?: string
  total_tables?: number
  unrelated_tables?: number
  center?: string
  depth?: number
}

export interface OwnerReference {
  from_owner: string
  to_owner: string
  fk_count: number
  examples: string[]
}

export interface SearchResult {
  tables?: { owner: string; name: string; type: string; comment: string | null }[]
  columns?: { owner: string; table: string; column: string; type: string; comment: string | null }[]
  comments?: { owner: string; table: string; column: string | null; comment: string }[]
  similar?: SimilarTable[]
  elapsed_ms: number
}

export interface SimilarTable {
  owner: string
  name: string
  type: string
  score: number
}

export interface RelatedTable {
  owner: string
  name: string
  direction: 'references' | 'referenced_by' | 'maybe_references' | 'maybe_referenced_by'
  via: string
  constraint?: string
}

export interface Related {
  foreign_keys: RelatedTable[]
  implicit: RelatedTable[]
  similar: SimilarTable[]
}

export interface TableRef {
  owner: string
  name: string
}
