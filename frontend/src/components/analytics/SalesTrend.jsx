import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ReferenceArea,
} from 'recharts'
import { fmtMoney } from '../../utils/format.js'
import { SegmentedControl } from './common.jsx'
import { chartColor } from './chartPalette.js'

const AXIS_TICK = { fontSize: 11, fill: 'var(--chart-axis, #5c6f68)' }

const METRIC_OPTIONS = [
  { value: 'revenue', label: 'Revenue' },
  { value: 'profit', label: 'Profit' },
]

/**
 * Sales trend graph — Track A "sales" snapshot.
 *
 * `data` is the frozen sales payload from analytics_snapshots:
 *   { current:{revenue,profit,orders}, change_pct:{revenue,profit,orders},
 *     series:[{key,label,revenue,profit,orders}], best:{by_revenue,by_profit},
 *     best_unit:'hours'|'days', period }
 *
 * Headline numbers live in the page KPI strip; this panel is the chart +
 * the best-hours/days visualization. The metric toggle here is lifted to
 * the page so the race section follows along.
 */
export default function SalesTrend({ data, metric = 'revenue', onMetricChange }) {
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
  const maxBest = Math.max(...(bestList || []).map((b) => b[metric] ?? 0), 1)

  return (
    <div className="analytics-panel">
      <div className="analytics-panel-head">
        <h3 className="card-title">Sales {isHourly ? 'by hour' : 'by day'}</h3>
        <div className="analytics-panel-controls">
          <SegmentedControl
            options={METRIC_OPTIONS}
            value={metric}
            onChange={onMetricChange}
            ariaLabel="Chart metric"
            size="sm"
          />
        </div>
      </div>

      <div className="chart-wrap">
        <ResponsiveContainer width="100%" height={280}>
          <LineChart data={chartData} margin={{ top: 10, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={chartColor('grid')} />
            <XAxis dataKey="name" tick={AXIS_TICK} interval="preserveStartEnd" stroke={chartColor('grid')} />
            <YAxis tick={AXIS_TICK} tickFormatter={(v) => fmtMoney(v)} width={72} stroke={chartColor('grid')} />
            <Tooltip
              contentStyle={{ borderRadius: 10, border: '1px solid var(--border-strong)', boxShadow: 'var(--shadow-2)' }}
              formatter={(v, key) => [fmtMoney(v), key]}
            />
            {bestSpan && (
              <ReferenceArea x1={bestSpan.start} x2={bestSpan.end}
                fill={chartColor('orders')} fillOpacity={0.1} />
            )}
            <Line type="monotone" dataKey="revenue" stroke={chartColor('revenue')}
              strokeWidth={2} dot={false} hide={metric === 'profit'} />
            <Line type="monotone" dataKey="profit" stroke={chartColor('profit')}
              strokeWidth={2} dot={false} hide={metric === 'revenue'} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="best-grid">
        <BestPanel title={`Best ${isHourly ? 'hours' : 'days'} · revenue`} list={data.best?.by_revenue} metric="revenue" max={maxBest} period={data.period} />
        <BestPanel title={`Best ${isHourly ? 'hours' : 'days'} · profit`} list={data.best?.by_profit} metric="profit" max={maxBest} period={data.period} />
      </div>
    </div>
  )
}

/** Best buckets as compact metric bars, not plain text. */
function BestPanel({ title, list, metric, max, period }) {
  return (
    <div className="card-sub">
      <h4>{title}</h4>
      {!list?.length ? (
        <p className="muted">No sales recorded this {period} yet.</p>
      ) : (
        <ol className="best-list best-list-bars">
          {list.map((b) => (
            <li key={b.key}>
              <span className="best-label">{b.label}</span>
              <span className="best-bar-track" aria-hidden="true">
                <span
                  className="best-bar"
                  style={{ width: `${Math.max(8, ((b[metric] ?? 0) / max) * 100)}%`, background: chartColor(metric) }}
                />
              </span>
              <strong className="best-fig">{fmtMoney(b[metric])}</strong>
              <span className="muted best-fig-sub">{b.orders} order{b.orders === 1 ? '' : 's'}</span>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
