import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, Legend, ReferenceArea,
} from 'recharts'
import { fmtMoney } from '../../utils/format.js'
import { DeltaChip } from './common.jsx'

const COLORS = { revenue: 'var(--primary, #2563eb)', profit: 'var(--success, #16a34a)' }

/**
 * Sales trend graph — Track A "sales" snapshot.
 *
 * `data` is the frozen sales payload from analytics_snapshots:
 *   { current:{revenue,profit,orders}, change_pct:{revenue,profit,orders},
 *     series:[{key,label,revenue,profit,orders}], best:{by_revenue,by_profit},
 *     best_unit:'hours'|'days', period }
 */
export default function SalesTrend({ data, metric = 'revenue' }) {
  if (!data?.series) return null
  const isHourly = data.best_unit === 'hours'

  const chartData = data.series.map((b) => ({
    name: b.label,
    revenue: b.revenue,
    profit: b.profit,
    orders: b.orders,
  }))

  // Shade the span that holds the best bucket(s) for the active metric.
  const bestList = metric === 'revenue' ? data.best?.by_revenue : data.best?.by_profit
  const bestSpan = bestList?.length
    ? { start: bestList[0].label, end: bestList[0].label }
    : null

  return (
    <div className="analytics-panel">
      <div className="analytics-panel-head">
        <h3 className="card-title">Sales {isHourly ? 'by hour' : 'by day'}</h3>
        <DeltaChip value={data.change_pct?.[metric]} label={`vs last ${data.period}`} />
      </div>

      <div className="stat-row">
        <div className="stat-box">
          <span className="stat-label">{metric === 'revenue' ? 'Revenue' : 'Profit'} this {data.period}</span>
          <span className="stat-value">{fmtMoney(data.current?.[metric])}</span>
          <span className="stat-sub muted">Prev: {fmtMoney(data.previous?.[metric])}</span>
        </div>
        <div className="stat-box">
          <span className="stat-label">Orders this {data.period}</span>
          <span className="stat-value">{data.current?.orders ?? 0}</span>
          <span className="stat-sub muted">Prev: {data.previous?.orders ?? 0}</span>
        </div>
      </div>

      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={chartData} margin={{ top: 10, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border, #e5e7eb)" />
            <XAxis dataKey="name" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
            <YAxis tick={{ fontSize: 11 }} tickFormatter={(v) => fmtMoney(v)} width={72} />
            <Tooltip formatter={(v, key) => [fmtMoney(v), key]} />
            <Legend />
            {bestSpan && (
              <ReferenceArea x1={bestSpan.start} x2={bestSpan.end}
                fill="var(--warning, #f59e0b)" fillOpacity={0.12} />
            )}
            <Line type="monotone" dataKey="revenue" stroke={COLORS.revenue}
              strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="profit" stroke={COLORS.profit}
              strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="best-grid">
        <div className="card-sub">
          <h4>Best {isHourly ? 'hours' : 'days'} · revenue</h4>
          <BestList list={data.best?.by_revenue} metric="revenue" />
        </div>
        <div className="card-sub">
          <h4>Best {isHourly ? 'hours' : 'days'} · profit</h4>
          <BestList list={data.best?.by_profit} metric="profit" />
        </div>
      </div>
    </div>
  )
}

function BestList({ list, metric }) {
  if (!list?.length) {
    return <p className="muted">No sales recorded this {metric === 'revenue' ? 'period' : ''} yet.</p>
  }
  return (
    <ol className="best-list">
      {list.map((b) => (
        <li key={b.key}>
          <span>{b.label}</span>
          <strong>{fmtMoney(b[metric])}</strong>
          <span className="muted">{b.orders} order{b.orders === 1 ? '' : 's'}</span>
        </li>
      ))}
    </ol>
  )
}
