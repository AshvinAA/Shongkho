import { useEffect, useState } from 'react'
import { AlertTriangle, Pencil, Plus, Trash2, UserRound } from 'lucide-react'
import * as employeesApi from '../api/employees.js'
import * as staffApi from '../api/staff.js'
import * as authApi from '../api/auth.js'
import { fmtMoney, fmtDate, fmtDateTime } from '../utils/format.js'
import {
  Avatar,
  Badge,
  Button,
  Card,
  CardHeader,
  DataTable,
  Drawer,
  ErrorState,
  Input,
  Modal,
  Select,
  StatCard,
  Tabs,
} from '../components/ui/index.jsx'

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

const TABS = [
  { id: 'details', label: 'Details', icon: UserRound },
  { id: 'warnings', label: 'Warnings' },
  { id: 'commission', label: 'Commission' },
]

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

  // ------------------------------------------------ add drawer
  const [addOpen, setAddOpen] = useState(false)
  const [addForm, setAddForm] = useState({ name: '', phone_number: '', position: '', salary: '', password: '', role: 'employee' })
  const [addError, setAddError] = useState(null)
  const [addBusy, setAddBusy] = useState(false)

  // ------------------------------------------------ edit drawer
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

  // ------------------------------------------------ roster table
  const columns = [
    {
      key: 'name',
      label: 'Name',
      render: (emp) => (
        <span className="table-person">
          <Avatar user={emp} size="xs" />
          <span className="cell-strong">{emp.name}</span>
        </span>
      ),
    },
    { key: 'phone_number', label: 'Phone' },
    {
      key: 'position',
      label: 'Position',
      getValue: (emp) => emp.position || '',
      render: (emp) => emp.position || '—',
    },
    {
      key: 'salary',
      label: 'Salary',
      align: 'right',
      getValue: (emp) => (emp.salary == null ? -1 : emp.salary),
      render: (emp) => (emp.salary != null ? <span className="ui-num">{fmtMoney(emp.salary)}</span> : '—'),
    },
    {
      key: 'user_type',
      label: 'Role',
      render: (emp) => <Badge variant={emp.user_type === 'owner' ? 'brand' : 'neutral'}>{emp.user_type}</Badge>,
    },
    {
      key: 'date_appointed',
      label: 'Joined',
      getValue: (emp) => emp.date_appointed || '',
      render: (emp) => <span className="muted">{fmtDate(emp.date_appointed)}</span>,
    },
    {
      key: 'sales',
      label: 'Sales (all-time)',
      getValue: (emp) => perfFor(emp.user_id)?.total_revenue ?? -1,
      render: (emp) => {
        const perf = perfFor(emp.user_id)
        return perf ? (
          <span className="ui-num">
            {perf.total_sales} txns · {fmtMoney(perf.total_revenue)}
          </span>
        ) : (
          'No sales yet'
        )
      },
    },
    {
      key: 'actions',
      label: 'Actions',
      sortable: false,
      render: (emp) => (
        <div className="row-actions">
          <Button variant="secondary" size="sm" onClick={() => openTab(emp)}>
            View
          </Button>
          <Button variant="secondary" size="sm" onClick={() => openEdit(emp)}>
            <Pencil size={13} aria-hidden="true" /> Edit
          </Button>
          <Button variant="danger" size="sm" onClick={() => setDeleteTarget(emp)}>
            <Trash2 size={13} aria-hidden="true" /> Delete
          </Button>
        </div>
      ),
    },
  ]

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Staff</h1>
          <p className="muted">Manage employee accounts, roles, warnings and commission</p>
        </div>
        <Button onClick={() => setAddOpen(true)}>
          <Plus size={16} aria-hidden="true" /> Add Employee
        </Button>
      </div>

      {error && <ErrorState onRetry={load}>{error}</ErrorState>}

      <Card>
        <CardHeader
          title="Employee Roster"
          subtitle={`${employees.length} team member${employees.length === 1 ? '' : 's'}`}
        />
        {loading ? (
          <div className="page-loading" role="status" aria-label="Loading staff">
            <div className="spinner" />
            <p className="muted">Loading staff…</p>
          </div>
        ) : employees.length === 0 ? (
          <p className="muted">No employees yet. Add your first team member.</p>
        ) : (
          <DataTable
            columns={columns}
            rows={employees}
            getRowKey={(emp) => emp.user_id}
            rowClassName={(emp) => (tabTarget?.user_id === emp.user_id ? 'row-active' : undefined)}
            empty={<p className="muted">No employees yet. Add your first team member.</p>}
          />
        )}
      </Card>

      {/* ---------------- Per-employee tab panel ---------------- */}
      {tabTarget && (
        <Card className="staff-tabcard">
          <div className="staff-tabhead">
            <div className="staff-tabperson">
              <Avatar user={tabTarget} size="sm" />
              <div>
                <div className="cell-strong">{tabTarget.name}</div>
                <div className="muted">{tabTarget.position || 'Staff member'} · #{tabTarget.user_id}</div>
              </div>
            </div>
            <Tabs
              tabs={TABS.map((t) =>
                t.id === 'warnings' ? { ...t, badge: warnings.length > 0 ? warnings.length : null } : t,
              )}
              active={tab}
              onChange={setTab}
              ariaLabel={`${tabTarget.name} details`}
            />
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setTabTarget(null)}
              aria-label="Close staff panel"
            >
              ✕ Close
            </Button>
          </div>

          {tabError && <div className="alert alert-error" role="alert">{tabError}</div>}
          {tabBusy && <div className="spinner" role="status" aria-label="Loading panel" />}

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
                    <StatCard label="Transactions (all-time)" value={perf.total_sales} />
                    <StatCard label="Revenue generated" value={fmtMoney(perf.total_revenue)} tone="revenue" />
                    <StatCard label="Profit generated" value={fmtMoney(perf.total_profit)} tone="profit" />
                    <StatCard
                      label="Commission policy"
                      value={commission?.rate != null ? `${commission.rate}% of ${commission.basis}` : 'Not set'}
                    />
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
                <Button variant="danger" size="sm" onClick={() => { setWarnOpen(true); setWarnError(null) }}>
                  <AlertTriangle size={14} aria-hidden="true" /> Issue Warning
                </Button>
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
                    <Select
                      id="comm-basis"
                      value={commForm.basis}
                      onChange={(e) => setCommForm((f) => ({ ...f, basis: e.target.value }))}
                    >
                      <option value="revenue">% of revenue generated</option>
                      <option value="profit">% of profit generated</option>
                    </Select>
                  </div>
                  <div className="form-group">
                    <label className="form-label" htmlFor="comm-rate">Rate (%)</label>
                    <Input
                      id="comm-rate"
                      type="number"
                      min="0"
                      max="100"
                      step="0.01"
                      placeholder="e.g. 5"
                      value={commForm.rate}
                      onChange={(e) => setCommForm((f) => ({ ...f, rate: e.target.value }))}
                    />
                  </div>
                  <div className="commission-actions">
                    <Button type="submit" loading={commBusy}>
                      {commBusy ? 'Saving…' : 'Save Policy'}
                    </Button>
                    {commission?.rate != null && (
                      <Button
                        type="button"
                        variant="secondary"
                        disabled={commBusy}
                        onClick={() => setCommForm((f) => ({ ...f, rate: '' }))}
                      >
                        Disable (clear rate, then save)
                      </Button>
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
        </Card>
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
          <div className="ui-overlay-footer">
            <Button type="button" variant="secondary" onClick={() => setWarnOpen(false)}>Cancel</Button>
            <Button type="submit" variant="danger" loading={warnBusy}>
              {warnBusy ? 'Issuing…' : 'Issue Warning'}
            </Button>
          </div>
        </form>
      </Modal>

      {/* ---------------- Add employee drawer ---------------- */}
      <Drawer open={addOpen} onClose={() => setAddOpen(false)} title="Add Employee">
        <form onSubmit={handleAddSubmit} noValidate>
          {addError && <div className="alert alert-error" role="alert">{addError}</div>}

          <div className="form-group">
            <label className="form-label" htmlFor="staff-name">Full Name *</label>
            <Input id="staff-name" name="name" type="text" value={addForm.name} onChange={handleAddChange} autoFocus />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="staff-phone">Phone Number *</label>
            <Input id="staff-phone" name="phone_number" type="tel" value={addForm.phone_number} onChange={handleAddChange} placeholder="017XXXXXXXX" />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="staff-password">Initial Password *</label>
            <Input id="staff-password" name="password" type="text" value={addForm.password} onChange={handleAddChange} placeholder="Shared with the employee" />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label" htmlFor="staff-position">Position</label>
              <Input id="staff-position" name="position" type="text" value={addForm.position} onChange={handleAddChange} placeholder="e.g. Cashier" />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="staff-salary">Salary ৳</label>
              <Input id="staff-salary" name="salary" type="number" min="0" step="0.01" value={addForm.salary} onChange={handleAddChange} />
            </div>
          </div>

          <div className="ui-overlay-footer">
            <Button type="button" variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button>
            <Button type="submit" loading={addBusy}>{addBusy ? 'Adding…' : 'Add Employee'}</Button>
          </div>
        </form>
      </Drawer>

      {/* ---------------- Edit employee drawer ---------------- */}
      <Drawer open={!!editTarget} onClose={() => setEditTarget(null)} title={`Edit ${editTarget?.name ?? ''}`}>
        <form onSubmit={handleEditSubmit} noValidate>
          {editError && <div className="alert alert-error" role="alert">{editError}</div>}

          <div className="form-group">
            <label className="form-label" htmlFor="estaff-name">Name</label>
            <Input id="estaff-name" name="name" type="text" value={editForm.name} onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))} />
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="estaff-phone">Phone Number</label>
            <Input id="estaff-phone" name="phone_number" type="tel" value={editForm.phone_number} onChange={(e) => setEditForm((f) => ({ ...f, phone_number: e.target.value }))} />
          </div>
          <div className="form-row">
            <div className="form-group">
              <label className="form-label" htmlFor="estaff-position">Position</label>
              <Input id="estaff-position" name="position" type="text" value={editForm.position} onChange={(e) => setEditForm((f) => ({ ...f, position: e.target.value }))} />
            </div>
            <div className="form-group">
              <label className="form-label" htmlFor="estaff-salary">Salary ৳</label>
              <Input id="estaff-salary" name="salary" type="number" min="0" step="0.01" value={editForm.salary} onChange={(e) => setEditForm((f) => ({ ...f, salary: e.target.value }))} />
            </div>
          </div>
          <div className="form-group">
            <label className="form-label" htmlFor="estaff-role">Role</label>
            <Select id="estaff-role" name="role" value={editForm.role} onChange={(e) => setEditForm((f) => ({ ...f, role: e.target.value }))}>
              <option value="employee">Employee</option>
              <option value="owner">Owner</option>
            </Select>
            <p className="form-hint info">Changing role converts the account type.</p>
          </div>

          <div className="ui-overlay-footer">
            <Button type="button" variant="secondary" onClick={() => setEditTarget(null)}>Cancel</Button>
            <Button type="submit" loading={editBusy}>{editBusy ? 'Saving…' : 'Save Changes'}</Button>
          </div>
        </form>
      </Drawer>

      {/* ---------------- Delete confirm ---------------- */}
      <Modal
        open={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="Delete Employee"
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDelete} loading={deleteBusy}>
              {deleteBusy ? 'Deleting…' : 'Delete'}
            </Button>
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
