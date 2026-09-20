import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'
import { RoleGate } from '../components/RoleGate.jsx'
import Avatar from '../components/Avatar.jsx'
import * as productsApi from '../api/products.js'
import * as salesApi from '../api/sales.js'
import * as employeesApi from '../api/employees.js'
import { fmtMoney, fmtDate, todayISO } from '../utils/format.js'

const LOW_STOCK_THRESHOLD = 5

/**
 * Owner-only metrics. Rendered through RoleGate as a COMPONENT (not inline
 * JSX) so `stats.performance` etc. are only evaluated when this actually
 * renders — inline JSX would evaluate eagerly and crash for employees,
 * whose stats never include the owner-only fields.
 */
function OwnerMetrics({ stats }) {
  return (
    <>
      <div className="stat-grid">
        <div className="card stat-card">
          <div className="stat-label">Today's Revenue</div>
          <div className="stat-value">{fmtMoney(stats.daily?.total_revenue)}</div>
          <div className="stat-sub muted">{stats.daily?.total_transactions ?? 0} transactions today</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">Today's Profit</div>
          <div className="stat-value">{fmtMoney(stats.daily?.total_profit)}</div>
          <div className="stat-sub muted">Across all staff</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">30-Day Revenue</div>
          <div className="stat-value">{fmtMoney(stats.monthly?.total_revenue)}</div>
          <div className="stat-sub muted">{stats.monthly?.total_transactions ?? 0} transactions</div>
        </div>
        <div className={`card stat-card ${stats.lowStock.length > 0 ? 'stat-warning' : ''}`}>
          <div className="stat-label">Low Stock</div>
          <div className="stat-value">{stats.lowStock.length}</div>
          <div className="stat-sub muted">
            {stats.lowStock.length > 0 ? (
              <Link to="/inventory">Restock needed →</Link>
            ) : (
              'All products healthy'
            )}
          </div>
        </div>
      </div>

      <div className="dashboard-columns">
        <div className="card">
          <div className="card-title">Top Performers (All Time)</div>
          {stats.performance?.length === 0 ? (
            <p className="muted">No employees registered yet. <Link to="/staff">Add staff →</Link></p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Employee</th>
                  <th>Sales</th>
                  <th>Revenue</th>
                  <th>Profit</th>
                </tr>
              </thead>
              <tbody>
                {(stats.performance ?? []).map((p) => (
                  <tr key={p.employee_id}>
                    <td>
                      <span className="table-person">
                        <Avatar user={{ name: p.employee_name }} size="xs" />
                        {p.employee_name}
                      </span>
                    </td>
                    <td>{p.total_sales}</td>
                    <td>{fmtMoney(p.total_revenue)}</td>
                    <td>{fmtMoney(p.total_profit)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <div className="card-title">Low Stock Alert (≤ {LOW_STOCK_THRESHOLD})</div>
          {stats.lowStock.length === 0 ? (
            <p className="muted">Everything is well stocked. 🎉</p>
          ) : (
            <ul className="low-stock-list">
              {stats.lowStock.slice(0, 8).map((p) => (
                <li key={p.product_id}>
                  <span className="table-person">
                    <Avatar product={p} size="xs" />
                    {p.product_name}
                  </span>
                  <span className={`stock-chip ${p.stock_quantity === 0 ? 'stock-out' : 'stock-low'}`}>
                    {p.stock_quantity === 0 ? 'Out of stock' : `${p.stock_quantity} left`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </>
  )
}

/** "My Store" card — where this employee works, who they work for, pay details. */
function MyStoreCard({ store }) {
  return (
    <div className="card store-card">
      <div className="card-title">🏬 My Store</div>
      <div className="store-card-body">
        <div className="store-owner">
          <Avatar user={{ name: store.owner_name, photo: store.owner_photo }} size="lg" />
          <div>
            <div className="store-name">{store.store_name || 'Store'}</div>
            <div className="muted">
              Owner: <strong>{store.owner_name || '—'}</strong>
            </div>
            {store.owner_phone && (
              <div className="muted">📞 {store.owner_phone}</div>
            )}
          </div>
        </div>

        <dl className="store-facts">
          <div className="store-fact">
            <dt>My Position</dt>
            <dd>{store.my_position || '—'}</dd>
          </div>
          <div className="store-fact">
            <dt>Monthly Salary</dt>
            <dd>{store.my_salary != null ? fmtMoney(store.my_salary) : '—'}</dd>
          </div>
          <div className="store-fact">
            <dt>Joined On</dt>
            <dd>{fmtDate(store.date_appointed)}</dd>
          </div>
          <div className="store-fact">
            <dt>Team Size</dt>
            <dd>{store.colleagues + 1} {store.colleagues === 0 ? 'person' : 'people'}</dd>
          </div>
        </dl>
      </div>
    </div>
  )
}

/** Employee-only view — same eager-evaluation rationale as OwnerMetrics. */
function EmployeeMetrics({ stats }) {
  return (
    <>
      {stats.myStore && <MyStoreCard store={stats.myStore} />}

      <div className="stat-grid">
        <div className="card stat-card">
          <div className="stat-label">My Sales Today</div>
          <div className="stat-value">{stats.todaysSales.length}</div>
          <div className="stat-sub muted">Transactions you processed</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">My Revenue Today</div>
          <div className="stat-value">{fmtMoney(stats.todayRevenue)}</div>
          <div className="stat-sub muted">Keep it up! 💪</div>
        </div>
        <div className="card stat-card">
          <div className="stat-label">All-Time Sales</div>
          <div className="stat-value">{stats.allTime?.total_sales ?? 0}</div>
          <div className="stat-sub muted">{fmtMoney(stats.allTime?.total_revenue)} earned for the store</div>
        </div>
        <div className={`card stat-card ${stats.lowStock.length > 0 ? 'stat-warning' : ''}`}>
          <div className="stat-label">Low Stock Items</div>
          <div className="stat-value">{stats.lowStock.length}</div>
          <div className="stat-sub muted">Tell the owner before they run out</div>
        </div>
      </div>

      <div className="dashboard-columns">
        <div className="card">
          <div className="card-title">Your Recent Transactions</div>
          {stats.todaysSales.length === 0 ? (
            <p className="muted">No sales today yet — <Link to="/pos">open the POS</Link> to start ringing up customers.</p>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Txn #</th>
                  <th>Time</th>
                  <th>Payment</th>
                  <th>Total</th>
                </tr>
              </thead>
              <tbody>
                {stats.todaysSales.slice(0, 8).map((s) => (
                  <tr key={s.transaction_id}>
                    <td>#{s.transaction_id}</td>
                    <td>{String(s.time).slice(0, 5)}</td>
                    <td>{s.payment_method}</td>
                    <td>{fmtMoney(s.total_revenue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <div className="card-title">Low Stock To Watch (≤ {LOW_STOCK_THRESHOLD})</div>
          {stats.lowStock.length === 0 ? (
            <p className="muted">Shelves are fully stocked. 🎉</p>
          ) : (
            <ul className="low-stock-list">
              {stats.lowStock.slice(0, 8).map((p) => (
                <li key={p.product_id}>
                  <span className="table-person">
                    <Avatar product={p} size="xs" />
                    {p.product_name}
                  </span>
                  <span className={`stock-chip ${p.stock_quantity === 0 ? 'stock-out' : 'stock-low'}`}>
                    {p.stock_quantity === 0 ? 'Out of stock' : `${p.stock_quantity} left`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </>
  )
}

/** Landing page with summary statistics, tailored per role. */
export default function Dashboard() {
  const { user } = useAuth()
  const [stats, setStats] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false

    async function load() {
      setError(null)
      try {
        const [products, sales] = await Promise.all([
          productsApi.listProducts({ limit: 1000 }),
          salesApi.listSales({ limit: 200 }),
        ])
        if (!Array.isArray(products) || !Array.isArray(sales)) {
          throw new Error('Unexpected server response while loading the dashboard.')
        }

        const today = todayISO()
        const todaysSales = sales.filter((s) => String(s.date).slice(0, 10) === today)
        const result = {
          productCount: products.length,
          todaysSales,
          todayRevenue: todaysSales.reduce((sum, s) => sum + (Number(s.total_revenue) || 0), 0),
          lowStock: products
            .filter((p) => p.stock_quantity <= LOW_STOCK_THRESHOLD)
            .sort((a, b) => a.stock_quantity - b.stock_quantity),
        }

        if (user?.role === 'owner') {
          const [daily, monthly, performance] = await Promise.all([
            salesApi.getSalesReport('daily'),
            salesApi.getSalesReport('monthly'),
            employeesApi.getPerformance({ limit: 100 }),
          ])
          result.daily = daily
          result.monthly = monthly
          result.performance = Array.isArray(performance)
            ? performance.sort((a, b) => b.total_revenue - a.total_revenue).slice(0, 5)
            : []
        }

        if (user?.role === 'employee') {
          const [myStore, allTime] = await Promise.all([
            employeesApi.getMyStore().catch(() => null),
            employeesApi.getMyAllTimePerformance().catch(() => null),
          ])
          result.myStore = myStore
          result.allTime = allTime
        }

        if (!cancelled) setStats(result)
      } catch (err) {
        if (!cancelled) setError(err.message)
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [user])

  if (error) {
    return (
      <div className="page">
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      </div>
    )
  }

  if (!stats) {
    return (
      <div className="page page-loading" role="status">
        <div className="spinner" />
        <p className="muted">Loading dashboard…</p>
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Welcome back, {user?.name?.split(' ')[0]} 👋</h1>
          <p className="muted">
            {user?.role === 'owner' ? 'Store owner view' : 'Employee view'} ·{' '}
            {new Date().toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
          </p>
        </div>
        <Link to="/pos" className="btn">
          🛒 Open POS
        </Link>
      </div>

      {/* ------------------------------------------------ */}
      {/* OWNER METRICS                                     */}
      {/* ------------------------------------------------ */}
      <RoleGate allowedRoles={['owner']}>
        <OwnerMetrics stats={stats} />
      </RoleGate>

      {/* ------------------------------------------------ */}
      {/* EMPLOYEE VIEW                                     */}
      {/* ------------------------------------------------ */}
      <RoleGate allowedRoles={['employee']}>
        <EmployeeMetrics stats={stats} />
      </RoleGate>
    </div>
  )
}
