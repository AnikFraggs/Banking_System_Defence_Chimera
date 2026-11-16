import { useCallback, useEffect, useState } from 'react'
import { listAnalystCases, listAnalystOrders, submitAnalystVerdict } from '../api'

const display = value => value === null || value === undefined || value === '' ? '—' : String(value)
const amount = order => {
  const numeric = Number(order.amount)
  if (!Number.isFinite(numeric)) return `${display(order.amount)} ${order.currency || ''}`.trim()
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: order.currency || 'USD' }).format(numeric)
  } catch {
    return `${numeric.toFixed(2)} ${order.currency || 'USD'}`
  }
}
const dateTime = value => {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

export default function AnalystOrdersTable({ token }) {
  const [orders, setOrders] = useState([])
  const [cases, setCases] = useState([])
  const [loading, setLoading] = useState(true)
  const [caseBusy, setCaseBusy] = useState('')
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [orderResult, caseResult] = await Promise.all([listAnalystOrders(token), listAnalystCases(token)])
      setOrders(Array.isArray(orderResult) ? orderResult : [])
      setCases(Array.isArray(caseResult) ? caseResult : [])
    } catch (requestError) {
      setError(requestError.message || 'Unable to load analyst decisions.')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { load() }, [load])

  const decide = async (caseId, verdict) => {
    setCaseBusy(caseId)
    setError('')
    try {
      const updated = await submitAnalystVerdict(token, caseId, verdict)
      setCases(current => current.map(item => item.id === caseId ? updated : item))
    } catch (requestError) {
      setError(requestError.message || 'Unable to submit the analyst verdict.')
    } finally {
      setCaseBusy('')
    }
  }

  return <>
    <section className="card checkout-analyst" aria-labelledby="analyst-heading">
    <div className="page-heading compact">
      <div>
        <p className="eyebrow">SERVER DECISION LOG</p>
        <h3 id="analyst-heading">Analyst decisions</h3>
        <p className="muted">A plain operational view of checkout outcomes and their server-provided reasons.</p>
      </div>
      <button type="button" className="secondary" onClick={load} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh decisions'}</button>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    {loading && orders.length === 0 ? <p className="muted">Loading analyst decisions…</p> : <div className="table-wrap">
      <table>
        <thead><tr><th>Updated</th><th>Order</th><th>Scenario</th><th>Amount</th><th>State</th><th>Score</th><th>Action</th><th>Reasons</th></tr></thead>
        <tbody>
          {orders.length === 0 ? <tr><td colSpan="8" className="muted">No analyst decisions returned.</td></tr> : orders.map(order => <tr key={order.id}>
            <td>{dateTime(order.updatedAt || order.createdAt)}</td>
            <td><code>{display(order.id)}</code>{order.simulated && <small className="checkout-table-label">SIMULATED</small>}</td>
            <td>{display(order.scenarioId)}</td>
            <td>{amount(order)}</td>
            <td>{display(order.state)}</td>
            <td>{display(order.score)}</td>
            <td>{display(order.action)}</td>
            <td>{Array.isArray(order.reasons) && order.reasons.length ? order.reasons.map((reason, index) => <div className="checkout-table-reason" key={`${reason.code || 'reason'}-${index}`}><strong>{display(reason.code)}</strong>{reason.message ? ` ${reason.message}` : ''}</div>) : '—'}</td>
          </tr>)}
        </tbody>
      </table>
    </div>}
    </section>

    <section className="card checkout-analyst" aria-labelledby="case-queue-heading">
      <div className="page-heading compact">
        <div>
          <p className="eyebrow">REVIEW QUEUE</p>
          <h3 id="case-queue-heading">Analyst cases</h3>
          <p className="muted">Review server-opened cases. Verdicts record analyst outcomes and do not alter settlement state.</p>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>Updated</th><th>Case</th><th>Order</th><th>Status</th><th>Verdict</th><th>Explanation</th><th>Review</th></tr></thead>
          <tbody>
            {cases.length === 0 ? <tr><td colSpan="7" className="muted">No analyst cases have been opened.</td></tr> : cases.map(item => <tr key={item.id}>
              <td>{dateTime(item.updatedAt || item.createdAt)}</td>
              <td><code>{display(item.id)}</code></td>
              <td><code>{display(item.orderId)}</code></td>
              <td>{display(item.status)}</td>
              <td>{display(item.analystVerdict)}</td>
              <td><div className="checkout-case-explanation">{display(item.explanation)}</div></td>
              <td>{item.status === 'OPEN' ? <div className="checkout-case-actions">
                {['FRAUD', 'BENIGN', 'INCONCLUSIVE'].map(verdict => <button key={verdict} type="button" className="secondary" disabled={caseBusy === item.id} onClick={() => decide(item.id, verdict)}>{verdict}</button>)}
              </div> : 'Resolved'}
            </td></tr>)}
          </tbody>
        </table>
      </div>
    </section>
  </>
}
