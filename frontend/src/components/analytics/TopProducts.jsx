import { useMemo, useState } from 'react'
import { fmtMoney } from '../../utils/format.js'
import { DeltaChip, SegmentedControl } from './common.jsx'
import { chartColor } from './chartPalette.js'
import { DataTable } from '../ui/index.jsx'

const METRIC_OPTIONS = [
  { value: 'revenue', label: 'Revenue' },
  { value: 'profit', label: 'Profit' },
]

/**
 * Top products — Track A "products" snapshot: a ranked BI table with a
 * revenue/profit switch (both rankings ship in the snapshot, so the
 * switch re-ranks locally), inline magnitude bars, margin, and unit
 * trend chips.
 *
 * `data`: { top_by_revenue, top_by_profit, bottom_by_revenue, period }
 * rows: { product_id, name, units, revenue, profit, margin_pct, units_change_pct }
 */
export default function TopProducts({ data }) {
  const [metric, setMetric] = useState('revenue')
  if (!data) return null

  const rows = (metric === 'revenue' ? data.top_by_revenue : data.top_by_profit) || []
  const maxVal = useMemo(() => Math.max(...rows.map((r) => r[metric] ?? 0), 1), [rows, metric])

  const columns = [
    {
      key: 'rank',
      label: '#',
      width: 48,
      sortable: false,
      render: (row) => {
        const i = rows.indexOf(row)
        return <span className={i < 3 ? `rank rank-${i + 1}` : 'rank'}>{i + 1}</span>
      },
    },
    { key: 'name', label: 'Product', render: (row) => <strong className="tp-name">{row.name}</strong> },
    { key: 'units', label: 'Units', align: 'right' },
    {
      key: metric,
      label: metric === 'revenue' ? 'Revenue' : 'Profit',
      align: 'right',
      render: (row) => (
        <span className="tp-value-cell">
          <span className="tp-bar-track" aria-hidden="true">
            <span className="tp-bar" style={{ width: `${Math.max(6, ((row[metric] ?? 0) / maxVal) * 100)}%`, background: chartColor(metric) }} />
          </span>
          <strong>{fmtMoney(row[metric])}</strong>
        </span>
      ),
    },
    {
      key: 'margin_pct',
      label: 'Margin',
      align: 'right',
      render: (row) =>
        row.margin_pct === null || row.margin_pct === undefined ? '—' : `${row.margin_pct}%`,
    },
    {
      key: 'units_change_pct',
      label: `Units vs last ${data.period}`,
      align: 'right',
      render: (row) => <DeltaChip value={row.units_change_pct} />,
    },
  ]

  return (
    <div className="analytics-panel">
      <div className="analytics-panel-head">
        <h3 className="card-title">Top products</h3>
        <div className="analytics-panel-controls">
          <SegmentedControl
            options={METRIC_OPTIONS}
            value={metric}
            onChange={setMetric}
            ariaLabel="Rank products by"
            size="sm"
          />
        </div>
      </div>

      {rows.length === 0 ? (
        <p className="muted">No product sales recorded this {data.period} yet.</p>
      ) : (
        <DataTable
          columns={columns}
          rows={rows}
          getRowKey={(row) => row.product_id}
          rowClassName={(_row, idx) => (idx === 0 ? 'ui-row-top1' : undefined)}
        />
      )}
    </div>
  )
}
