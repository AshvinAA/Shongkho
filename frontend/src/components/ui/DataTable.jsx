import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ArrowDownUp } from 'lucide-react'

/**
 * DataTable — BI table primitive.
 *
 *   columns: [{ key, label, align?: 'left'|'right'|'center', sortable?,
 *               width?, render?(row) }]
 *   rows:    array of objects
 *   getRowKey(row) — stable React key
 *   sortable (default true) — click header to sort; managed internally
 *   dense — tighter rows
 *   empty — rendered in tbody when rows is empty
 *
 * Sticky header, 1px row rules, right-aligned tabular numerics for
 * align="right" columns.
 */
export default function DataTable({ columns, rows, getRowKey, sortable = true, dense = false, empty = null, className = '' }) {
  const [sort, setSort] = useState(null) // { key, dir: 'asc' | 'desc' }

  const sortedRows = useMemo(() => {
    if (!sort) return rows
    const col = columns.find((c) => c.key === sort.key)
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const av = col?.getValue ? col.getValue(a) : a[sort.key]
      const bv = col?.getValue ? col.getValue(b) : b[sort.key]
      if (av === bv) return 0
      if (av === null || av === undefined) return 1
      if (bv === null || bv === undefined) return -1
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
      return String(av).localeCompare(String(bv)) * dir
    })
  }, [rows, columns, sort])

  function toggleSort(key) {
    setSort((s) => (s?.key !== key ? { key, dir: 'asc' } : s.dir === 'asc' ? { key, dir: 'desc' } : null))
  }

  return (
    <div className={`ui-table-wrap ${dense ? 'ui-table-dense' : ''} ${className}`}>
      <table className="ui-table">
        <thead>
          <tr>
            {columns.map((col) => {
              const isSorted = sort?.key === col.key
              const SortIcon = !sortable || col.sortable === false ? null : isSorted ? (sort.dir === 'asc' ? ArrowUp : ArrowDown) : ArrowDownUp
              return (
                <th
                  key={col.key}
                  style={col.width ? { width: col.width } : undefined}
                  className={`${col.align === 'right' ? 'ui-th-right' : col.align === 'center' ? 'ui-th-center' : ''} ${
                    SortIcon ? 'ui-th-sortable' : ''
                  }`}
                  aria-sort={isSorted ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                >
                  {SortIcon ? (
                    <button type="button" className="ui-th-btn" onClick={() => toggleSort(col.key)}>
                      <span>{col.label}</span>
                      <SortIcon size={12} aria-hidden="true" />
                    </button>
                  ) : (
                    col.label
                    )
                  }
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {sortedRows.length === 0 && empty ? (
            <tr>
              <td colSpan={columns.length}>{empty}</td>
            </tr>
          ) : (
            sortedRows.map((row) => (
              <tr key={getRowKey ? getRowKey(row) : row.id ?? row.key ?? JSON.stringify(row)}>
                {columns.map((col) => (
                  <td key={col.key} className={col.align === 'right' ? 'ui-td-right' : col.align === 'center' ? 'ui-td-center' : ''}>
                    {col.render ? col.render(row) : row[col.key]}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}
