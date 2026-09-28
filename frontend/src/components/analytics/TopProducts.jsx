import { useState } from 'react'
import { fmtMoney } from '../../utils/format.js'
import { DeltaChip, SegmentedControl } from './common.jsx'

const METRIC_OPTIONS = [
  { value: 'revenue', label: 'Revenue' },
  { value: 'profit', label: 'Profit' },
]

/**
 * Top products — Track A "products" snapshot: a ranked table with a
 * revenue/profit switch (both rankings ship in the snapshot, so the
 * switch re-ranks locally) and per-product unit trends.
 *
 * `data`: { top_by_revenue, top_by_profit, bottom_by_revenue, period }
 * rows: { product_id, name, units, revenue, profit, margin_pct, units_change_pct }
 */
export default function TopProducts({ data }) {
  const [metric, setMetric] = useState('revenue')
  if (!data) return null

  const rows = (metric === 'revenue' ? data.top_by_revenue : data.top_by_profit) || []

  return (
    <div className="analytics-panel">
      <div className="analytics-panel-head">
        <h3 className="card-title">Top products</h3>
        <SegmentedControl
          options={METRIC_OPTIONS}
          value={metric}
          onChange={setMetric}
          ariaLabel="Rank products by"
        />
      </div>

      {rows.length === 0 ? (
        <p className="muted">No product sales recorded this {data.period} yet.</p>
      ) : (
        <div className="table-scroll">
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Product</th>
                <th className="num">Units</th>
                <th className="num">{metric === 'revenue' ? 'Revenue' : 'Profit'}</th>
                <th className="num">Margin</th>
                <th className="num">Units vs last {data.period}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.product_id} className={i === 0 ? 'rank-row-1' : undefined}>
                  <td className={i < 3 ? `rank rank-${i + 1}` : 'rank'}>{i + 1}</td>
                  <td>{row.name}</td>
                  <td className="num">{row.units}</td>
                  <td className="num"><strong>{fmtMoney(row[metric])}</strong></td>
                  <td className="num">{row.margin_pct === null || row.margin_pct === undefined ? '—' : `${row.margin_pct}%`}</td>
                  <td className="num"><DeltaChip value={row.units_change_pct} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
