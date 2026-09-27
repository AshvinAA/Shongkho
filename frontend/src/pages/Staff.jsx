import { useEffect, useState } from 'react'
import * as employeesApi from '../api/employees.js'
import * as staffApi from '../api/staff.js'
import * as authApi from '../api/auth.js'
import Modal from '../components/Modal.jsx'
import Avatar from '../components/Avatar.jsx'
import { fmtMoney, fmtDate, fmtDateTime } from '../utils/format.js'

/**
 * Owner-only staff management: roster, per-employee sales performance,
 * adding employees, role changes (owner ⇄ employee) and deletion.
 *
 * Each staff member has their own TAB (panel under the roster) with
 * three sections:
 *   - Details   — profile facts + all-time sales performance
 *   - Warnings  — issue a formal warning (with a reason) and review
 *                 the history; the employee sees the same list
 *   - Commission— set the payout policy: a % of the revenue or profit
 *                 the employee generates (owner's choice), which then
 *                 shows on the employee's own dashboard
 */

const TABS = ['details', 'warnings', 'commission']

export default function Staff() {
  // ------------------------------------------------ roster
  const [employees, setEmployees] = useState([])
  const [performance, setPerformance] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // ------------------------------------------------ per-staff tabs
  // tabTarget: the employee whose panel is open; tab: active section.
  const [tabTarget, setTabTarget] = useState(null)
  const [tab, setTab] = useState('details')

  // ------------------------------------------------ tab data (per target)
  const [warnings, setWarnings] = useState([])
  const [commission, setCommission] = useState(null)
  const [tabBusy, setTabBusy] = useState(false)
  const [tabError, setTabError] = useState(null)

  // ------------------------------------------------ issue-warning form
  const [warnOpen, setWarnOpen] = useState(false)
  const [warnReason, setWarnReason] = useState('')
  const [warnError, setWarnError] = useState(null)
  const [warnBusy, setWarnBusy] = useState(false)

  // ------------------------------------------------ commission form
  const [commForm, setCommForm] = useState({ basis: 'revenue', rate: '' })
  const [commBusy, setCommBusy] = useState(false)
  const [commError, setCommError] = useState(null)

  // ------------------------------------------------ add modal
  const [addOpen, setAddOpen] = useState(false)
  const [addForm, setAddForm] = useState({ name: '', phone_number: '', position: '', salary: '', password: '', role: 'employee' })
  const [addError, setAddError] = useState(null)
  const [addBusy, setAddBusy] = useState(false)

  // ------------------------------------------------ edit modal
  const [editTarget, setEditTarget] = useState(null)
  const [editForm, setEditForm] = useState({ name: '', phone_number: '', position: '', salary: '', role: 'employee' })
  const [editError, setEditError] = useState(null)
  const [editBusy, setEditBusy] = useState(false)

  // ------------------------------------------------ delete confirm
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleteBusy, setDeleteBusy] = useState(false)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const [roster, perf] = await Promise.all([
        employeesApi.listEmployees({ limit: 500 }),
        employeesApi.getPerformance({ limit: 500 }),
      ])
      setEmployees(roster)
      setPerformance(perf)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  function perfFor(userId) {
    return performance.find((p) => p.employee_id === userId) || null
  }

  // ------------------------------------------------ tab panel data
  async function openTab(emp, section = 'details') {
    setTabTarget(emp)
    setTab(section)
    setTabError(null)
    setWarnError(null)
    setCommError(null)
    setWarnReason('')
    setCommForm({ basis: 'revenue', rate: '' })
    setWarnings([])
    setCommission(null)
    await Promise.all([loadWarnings(emp), loadCommission(emp)])
  }

  async function loadWarnings(emp) {
    try {
      setWarnings(await staffApi.listWarnings(emp.user_id))
    } catch (err) {
      setTabError(err.message)
    }
  }

  async function loadCommission(emp) {
    try {
      const row = await staffApi.getCommission(emp.user_id)
      setCommission(row)
      if (row.rate != null) {
        setCommForm({ basis: row.basis || 'revenue', rate: String(row.rate) })
      }
    } catch (err) {
      setTabError(err.message)
    }
  }

  // ------------------------------------------------ issue a warning
  async function handleWarnSubmit(e) {
    e.preventDefault()
    if (!warnReason.trim()) {
      setWarnError('Please give a reason for the warning.')
      return
    }
    setWarnBusy(true)
    setWarnError(null)
    try {
      await staffApi.issueWarning(tabTarget.user_id, warnReason.trim())
      setWarnOpen(false)
      setWarnReason('')
      await loadWarnings(tabTarget)
    } catch (err) {
      setWarnError(err.message)
    } finally {
      setWarnBusy(false)
    }
  }

  // ------------------------------------------------ set commission
  async function handleCommissionSubmit(e) {
    e.preventDefault()
    setCommBusy(true)
    setCommError(null)
    try {
      const rate = commForm.rate === '' ? null : Number(commForm.rate)
      if (rate != null && (!Number.isFinite(rate) || rate <= 0 || rate > 100)) {
        throw new Error('Rate must be between 0 and 100 (leave empty to disable).')
      }
      const saved = await staffApi.setCommission(tabTarget.user_id, {
        basis: commForm.basis,
        rate,
      })
      setCommission(saved)
      await loadCommission(tabTarget)
    } catch (err) {
      setCommError(err.message)
    } finally {
      setCommBusy(false)
    }
  }

  // ------------------------------------------------ add employee
  function handleAddChange(e) {
    const { name, value } = e.target
    setAddForm((f) => ({ ...f, [name]: value }))
  }

  async function handleAddSubmit(e) {
    e.preventDefault()
    setAddBusy(true)
    setAddError(null)
    try {
      const payload = {
        name: addForm.name.trim(),
        phone_number: addForm.phone_number.trim(),
        password: addForm.password,
        role: 'employee',
      }
      if (addForm.position.trim()) payload.position = addForm.position.trim()
      if (addForm.salary) payload.salary = Number(addForm.salary)
      await authApi.registerEmployee(payload)
      setAddOpen(false)
      setAddForm({ name: '', phone_number: '', position: '', salary: '', password: '', role: 'employee' })
      await load()
    } catch (err) {
      setAddError(err.message)
    } finally {
      setAddBusy(false)
    }
  }

  // ------------------------------------------------ edit employee
  function openEdit(emp) {
    setEditTarget(emp)
    setEditForm({
      name: emp.name || '',
      phone_number: emp.phone_number || '',
      position: emp.position || '',
      salary: emp.salary ?? '',
      role: emp.user_type || 'employee',
    })
    setEditError(null)
  }

  async function handleEditSubmit(e) {
    e.preventDefault()
    setEditBusy(true)
    setEditError(null)
    try {
      const payload = {
        name: editForm.name.trim(),
        phone_number: editForm.phone_number.trim(),
        position: editForm.position.trim() || null,
        role: editForm.role,
      }
      if (editForm.salary) payload.salary = Number(editForm.salary)
      await employeesApi.updateEmployee(editTarget.user_id, payload)
      setEditTarget(null)
      await load()
    } catch (err) {
      setEditError(err.message)
    } finally {
      setEditBusy(false)
    }
  }

  // ------------------------------------------------ delete employee
  async function handleDelete() {
    setDeleteBusy(true)
    try {
      await employeesApi.deleteEmployee(deleteTarget.user_id)
      if (tabTarget?.user_id === deleteTarget.user_id) setTabTarget(null)
      setDeleteTarget(null)
      await load()
    } catch (err) {
      setError(err.message)
      setDeleteTarget(null)
    } finally {
      setDeleteBusy(false)
    }
  }

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Staff</h1>
          <p className="muted">Manage employee accounts, roles, warnings and commission</p>
        </div>
        <button type="button" className="btn" onClick={() => setAddOpen(true)}>
          ＋ Add Employee
        </button>
      </div>

      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}

      <div className="card">
        <div className="card-title">Employee Roster</div>
        {loading ? (
          <div className="page-loading" role="status">
            <div className="spinner" />
            <p className="muted">Loading staff…</p>
          </div>
        ) : employees.length === 0 ? (
          <p className="muted">No employees yet. Add your first team member.</p>
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Name</th>
                  <th>Phone</th>
                  <th>Position</th>
                  <th>Salary</th>
                  <th>Role</th>
                  <th>Joined</th>
                  <th>Sales (all-time)</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {employees.map((emp) => {
                  const perf = perfFor(emp.user_id)
                  return (
                    <tr
                      key={emp.user_id}
                      className={tabTarget?.user_id === emp.user_id ? 'row-active' : undefined}
                    >
                      <td>#{emp.user_id}</td>
                      <td>
                        <span className="table-person">
                          <Avatar user={emp} size="xs" />
                          <span className="cell-strong">{emp.name}</span>
                        </span>
                      </td>
                      <td>{emp.phone_number}</td>
                      <td>{emp.position || '—'}</td>
                      <td>{emp.salary != null ? fmtMoney(emp.salary) : '—'}</td>
                      <td>
                        <span className={`role-badge role-${emp.user_type}`}>{emp.user_type}</span>
                      </td>
                      <td className="muted">{fmtDate(emp.date_appointed)}</td>
                      <td>
                        {perf
                          ? `${perf.total_sales} txns · ${fmtMoney(perf.total_revenue)}`
                          : 'No sales yet'}
                      </td>
                      <td>
                        <div className="row-actions">
                          <button type="button" className="btn btn-outline btn-sm" onClick={() => openTab(emp)}>
                            View
                          </button>
                          <button type="button" className="btn btn-outline btn-sm" onClick={() => openEdit(emp)}>
                            Edit
                          </button>
                          <button type="button" className="btn btn-danger btn-sm" onClick={() => setDeleteTarget(emp)}>
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ---------------- Per-employee tab panel ---------------- */}
      {tabTarget && (
        <div className="card staff-tabcard">
          <div className="staff-tabhead">
            <div className="staff-tabperson">
              <Avatar user={tabTarget} size="sm" />
              <div>
                <div className="cell-strong">{tabTarget.name}</div>
                <div className="muted">{tabTarget.position || 'Staff member'} · #{tabTarget.user_id}</div>
              </div>
            </div>
            <div className="staff-tabs" role="tablist" aria-label={`${tabTarget.name} details`}>
              {TABS.map((t) => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={tab === t}
                  className={`staff-tab ${tab === t ? 'staff-tab-active' : ''}`}
                  onClick={() => setTab(t)}
                >
                  {t === 'details' && 'Details'}
                  {t === 'warnings' && (
                    <>
                      Warnings
                      {warnings.length > 0 && (
                        <span className="warn-badge" title={`${warnings.length} warning(s)`}>
                          {warnings.length}
                        </span>
                      )}
                    </>
                  )}
                  {t === 'commission' && 'Commission'}
                </button>
              ))}
            </div>
            <button
              type="button"
              className="btn btn-outline btn-sm"
              onClick={() => setTabTarget(null)}
              aria-label="Close staff panel"
            >
              ✕ Close
            </button>
          </div>

          {tabError && <div className="alert alert-error" role="alert">{tabError}</div>}

          {/* ---- Details tab ---- */}
          {tab === 'details' && (
            <div className="staff-tabbody">
              <dl className="store-facts">
                <div className="store-fact">
                  <dt>Phone</dt>
                  <dd>{tabTarget.phone_number || '—'}</dd>
                </div>
                <div className="store-fact">
                  <dt>Position</dt>
                  <dd>{tabTarget.position || '—'}</dd>
                </div>
                <div className="store-fact">
                  <dt>Monthly Salary</dt>
                  <dd>{tabTarget.salary != null ? fmtMoney(tabTarget.salary) : '—'}</dd>
                </div>
                <div className="store-fact">
                  <dt>Joined On</dt>
                  <dd>{fmtDate(tabTarget.date_appointed)}</dd>
                </div>
              </dl>
              {(() => {
                const perf = perfFor(tabTarget.user_id)
                if (!perf) return <p className="muted">No sales recorded yet.</p>
                return (
                  <div className="stat-grid" style={{ marginTop: '0.75rem' }}>
                    <div className="card stat-card">
                      <div className="stat-label">Transactions (all-time)</div>
                      <div className="stat-value">{perf.total_sales}</div>
                    </div>
                    <div className="card stat-card">
                      <div className="stat-label">Revenue generated</div>
                      <div className="stat-value">{fmtMoney(perf.total_revenue)}</div>
                    </div>
                    <div className="card stat-card">
                      <div className="stat-label">Profit generated</div>
                      <div className="stat-value">{fmtMoney(perf.total_profit)}</div>
                    </div>
                    <div className="card stat-card">
                      <div className="stat-label">Commission policy</div>
                      <div className="stat-value">
                        {commission?.rate != null
                          ? `${commission.rate}% of ${commission.basis}`
                          : 'Not set'}
                      </div>
                    </div>
                  </div>
                )
              })()}
            </div>
          )}

          {/* ---- Warnings tab ---- */}
          {tab === 'warnings' && (
            <div className="staff-tabbody">
              <div className="staff-tabbody-head">
                <p className="muted" style={{ margin: 0 }}>
                  Formal warnings are visible to the employee on their own dashboard.
                </p>
                <button type="button" className="btn btn-danger btn-sm" onClick={() => { setWarnOpen(true); setWarnError(null) }}>
                  ⚠ Issue Warning
                </button>
              </div>
              {warnings.length === 0 ? (
                <p className="muted">No warnings on record. 🎉</p>
              ) : (
                <ul className="warn-list">
                  {warnings.map((w) => (
                    <li key={w.id} className="warn-item">
                      <div className="warn-item-head">
                        <strong>{fmtDateTime(w.created_at)}</strong>
                        <span className="muted">by {w.issued_by_name || `Owner #${w.issued_by}`}</span>
                      </div>
                      <p className="warn-reason">{w.reason}</p>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* ---- Commission tab ---- */}
          {tab === 'commission' && (
            <div className="staff-tabbody">
              <p className="muted" style={{ marginTop: 0 }}>
                Commission is a percentage of the revenue <em>or</em> profit this employee
                generates — your choice. It is computed live from their sales and shows on
                their dashboard immediately.
              </p>
              <form onSubmit={handleCommissionSubmit} className="commission-form" noValidate>
                {commError && <div className="alert alert-error" role="alert">{commError}</div>}
                <div className="commission-fields">
                  <div className="form-group">
                    <label className="form-label" htmlFor="comm-basis">Commission basis</label>
                    <select
                      id="comm-basis"
                      className="form-control"
                      value={commForm.basis}
                      onChange={(e) => setCommForm((f) => ({ ...f, basis: e.target.value }))}
                    >
                      <option value="revenue">% of revenue generated</option>
                      <option value="profit">% of profit generated</option>
                    </select>
                  </div>
                  <div className="form-group">
                    <label className="form-label" htmlFor="comm-rate">Rate (%)</label>
                    <input
                      id="comm-rate"
                      type="number"
                      min="0"
                      max="100"
                      step="0.01"
                      className="form-control"
                      placeholder="e.g. 5"
                      value={commForm.rate}
                      onChange={(e) => setCommForm((f) => ({ ...f, rate: e.target.value }))}
                    />
                  </div>
                  <div className="commission-actions">
                    <button type="submit" className="btn" disabled={commBusy}>
                      {commBusy ? 'Saving…' : 'Save Policy'}
                    </button>
                    {commission?.rate != null && (
                      <button
                        type="button"
                        className="btn btn-outline"
                        disabled={commBusy}
                        onClick={() => setCommForm((f) => ({ ...f, rate: '' }))}
                      >
                        Disable (clear rate, then save)
                      </button>
                    )}
                  </div>
                </div>
              </form>
              <div className={`commission-status ${commission?.rate != null ? 'commission-on' : ''}`}>
                {commission?.rate != null ? (
                  <>
                    ✅ Active: <strong>{commission.rate}% of {commission.basis}</strong> —
                    visible on {tabTarget.name.split(' ')[0]}'s dashboard.
                  </>
                ) : (
                  <>No commission policy set for this employee.</>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* ---------------- Issue warning modal ---------------- */}
      <Modal open={warnOpen} onClose={() => setWarnOpen(false)} title={`Warn ${tabTarget?.name ?? ''}`}>
        <form onSubmit={handleWarnSubmit} noValidate>
          {warnError && <div className="alert alert-error" role="alert">{warnError}</div>}
          <div className="form-group">
            <label className="form-label" htmlFor="warn-reason">Reason *</label>
            <textarea
              id="warn-reason"
              className="form-control"
              rows={4}
              placeholder="What happened? Be specific — the employee will see this."
              value={warnReason}
              onChange={(e) => setWarnReason(e.target.value)}
              autoFocus
            />
            <p className="form-hint">The employee sees this warning and the reason on their dashboard.</p>
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-outline" onClick={() => setWarnOpen(false)}>Cancel</button>
            <button type="submit" className="btn btn-danger" disabled={warnBusy}>
              {warnBusy ? 'Issuing…' : 'Issue Warning'}
            </button>
          </div>
        </form>
      </Modal>

      {/* ---------------- Add employee modal ---------------- */}
      <Modal open={addOpen} onClose={() => setAddOpen(false)} title="Add Employee">
        <form onSubmit={handleAddSubmit} noValidate>
          {addError && <div className="alert alert-error" role="alert">{addError}</div>}

          <div className="form-group">
            <label className="form-label" htmlFor="staff-name">Full Name *</label>
            <input id="staff-name" name="name" type="text" className="form-control" value={addForm.name} onChange={handleAddChange} autoFocus />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="staff-phone">Phone Number *</label>
            <input id="staff-phone" name="phone_number" type="tel" className="form-control" value={addForm.phone_number} onChange={handleAddChange} placeholder="017XXXXXXXX" />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="staff-password">Initial Password *</label>
            <input id="staff-password" name="password" type="text" className="form-control" value={addForm.password} onChange={handleAddChange} placeholder="Shared with the employee" />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label" htmlFor="staff-position">Position</label>
              <input id="staff-position" name="position" type="text" className="form-control" value={addForm.position} onChange={handleAddChange} placeholder="e.g. Cashier" />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="staff-salary">Salary ৳</label>
              <input id="staff-salary" name="salary" type="number" min="0" step="0.01" className="form-control" value={addForm.salary} onChange={handleAddChange} />
            </div>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-outline" onClick={() => setAddOpen(false)}>Cancel</button>
            <button type="submit" className="btn" disabled={addBusy}>{addBusy ? 'Adding…' : 'Add Employee'}</button>
          </div>
        </form>
      </Modal>

      {/* ---------------- Edit employee modal ---------------- */}
      <Modal open={!!editTarget} onClose={() => setEditTarget(null)} title={`Edit ${editTarget?.name ?? ''}`}>
        <form onSubmit={handleEditSubmit} noValidate>
          {editError && <div className="alert alert-error" role="alert">{editError}</div>}

          <div className="form-group">
            <label className="form-label" htmlFor="estaff-name">Name</label>
            <input id="estaff-name" name="name" type="text" className="form-control" value={editForm.name} onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))} />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="estaff-phone">Phone Number</label>
            <input id="estaff-phone" name="phone_number" type="tel" className="form-control" value={editForm.phone_number} onChange={(e) => setEditForm((f) => ({ ...f, phone_number: e.target.value }))} />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label" htmlFor="estaff-position">Position</label>
              <input id="estaff-position" name="position" type="text" className="form-control" value={editForm.position} onChange={(e) => setEditForm((f) => ({ ...f, position: e.target.value }))} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="estaff-salary">Salary ৳</label>
              <input id="estaff-salary" name="salary" type="number" min="0" step="0.01" className="form-control" value={editForm.salary} onChange={(e) => setEditForm((f) => ({ ...f, salary: e.target.value }))} />
            </div>
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="estaff-role">Role</label>
            <select id="estaff-role" name="role" className="form-control" value={editForm.role} onChange={(e) => setEditForm((f) => ({ ...f, role: e.target.value }))}>
              <option value="employee">Employee</option>
              <option value="owner">Owner</option>
            </select>
            <p className="form-hint info">Changing role converts the account type.</p>
          </div>

          <div className="modal-footer">
            <button type="button" className="btn btn-outline" onClick={() => setEditTarget(null)}>Cancel</button>
            <button type="submit" className="btn" disabled={editBusy}>{editBusy ? 'Saving…' : 'Save Changes'}</button>
          </div>
        </form>
      </Modal>

      {/* ---------------- Delete confirm ---------------- */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Employee"
        footer={
          <>
            <button type="button" className="btn btn-outline" onClick={() => setDeleteTarget(null)}>Cancel</button>
            <button type="button" className="btn btn-danger" onClick={handleDelete} disabled={deleteBusy}>
              {deleteBusy ? 'Deleting…' : 'Delete'}
            </button>
          </>
        }
      >
        <p>
          Delete <strong>{deleteTarget?.name}</strong>'s account?
        </p>
        <p className="muted">Their past sales are kept in the transaction history.</p>
      </Modal>
    </div>
  )
}
