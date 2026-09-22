import { useState } from 'react'
import { fmtMoney } from '../../utils/format.js'
import { DeltaChip } from './common.jsx'

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
        <h3 className="card-title">Top products — ranked by {metric}</h3>
        <DeltaChipNeutral />
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
                <th>Units</th>
                <th>{metric === 'revenue' ? 'Revenue' : 'Profit'}</th>
                <th>Margin</th>
                <th>Units vs last {data.period}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr key={row.product_id}>
                  <td className={i < 3 ? `rank rank-${i + 1}` : 'rank'}>{i + 1}</td>
                  <td>{row.name}</td>
                  <td>{row.units}</td>
                  <td><strong>{fmtMoney(row[metric])}</strong></td>
                  <td>{row.margin_pct === null || row.margin_pct === undefined ? '—' : `${row.margin_pct}%`}</td>
                  <td><DeltaChip value={row.units_change_pct} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="switch-hint muted">
        Showing {metric} ranking ·{' '}
        <button type="button" className="link-btn" onClick={() => setMetric(metric === 'revenue' ? 'profit' : 'revenue')}>
          switch to {metric === 'revenue' ? 'profit' : 'revenue'}
        </button>
      </div>
    </div>
  )
}

/** Placeholder chip — the real period delta lives on the sales panel. */
function DeltaChipNeutral() {
  return <span className="muted">Units trend compares to the previous {`period`}</span>
}
