import { useEffect, useState } from 'react'
import * as employeesApi from '../api/employees.js'
import * as authApi from '../api/auth.js'
import Modal from '../components/Modal.jsx'
import { fmtMoney, fmtDate } from '../utils/format.js'

/**
 * Owner-only staff management: roster, per-employee sales performance,
 * adding employees, role changes (owner ⇄ employee) and deletion.
 */
export default function Staff() {
  // ------------------------------------------------ roster
  const [employees, setEmployees] = useState([])
  const [performance, setPerformance] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

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
          <p className="muted">Manage employee accounts, roles and performance</p>
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
                    <tr key={emp.user_id}>
                      <td>#{emp.user_id}</td>
                      <td className="cell-strong">{emp.name}</td>
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
