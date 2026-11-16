import { useCallback, useEffect, useRef, useState } from 'react'
import PayPalCheckoutButton from './PayPalCheckoutButton'
import StepUpDialog from './StepUpDialog'
import useSessionTelemetry from './useSessionTelemetry'
import { createCheckoutOrder, getCheckoutOrder } from './api'
import ScenarioCards from './simulator/ScenarioCards'
import AnalystOrdersTable from './analyst/AnalystOrdersTable'
import ReceiptView from './receipts/ReceiptView'
import { RefreshCw, AlertCircle, CheckCircle, X, Clock, Shield, CreditCard, ExternalLink } from 'lucide-react'

const TERMINAL_STATES = new Set(['CAPTURED', 'BLOCKED', 'VOIDED', 'EXPIRED'])
const display = value => value === null || value === undefined || value === '' ? '—' : String(value)
const needsStepUp = order => Boolean(order?.stepUpRequired || order?.state === 'STEP_UP')

function formatAmount(order) {
  const numeric = Number(order?.amount)
  if (!Number.isFinite(numeric)) return `${display(order?.amount)} ${order?.currency || ''}`.trim()
  try {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: order.currency || 'USD' }).format(numeric)
  } catch {
    return `${numeric.toFixed(2)} ${order.currency || 'USD'}`
  }
}

function formatDate(value) {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString()
}

function OrderIdentifier({ label, value }) {
  return (
    <div className="checkout-identifier">
      <span>{label}</span>
      <code>{display(value)}</code>
    </div>
  )
}

function OrderDetails({ order }) {
  const reasons = Array.isArray(order?.reasons) ? order.reasons : []
  
  const getStateClass = (state) => {
    switch (state?.toLowerCase()) {
      case 'captured':
      case 'authorized':
        return 'checkout-state-captured'
      case 'blocked':
      case 'voided':
      case 'expired':
        return 'checkout-state-blocked'
      case 'step_up':
        return 'checkout-state-step_up'
      case 'created':
        return 'checkout-state-created'
      default:
        return 'checkout-state-created'
    }
  }

  const getActionClass = (action) => {
    if (!action) return ''
    const a = action.toLowerCase()
    if (a.includes('capture') || a.includes('approve')) return 'text-success'
    if (a.includes('block') || a.includes('deny') || a.includes('void')) return 'text-danger'
    if (a.includes('challenge') || a.includes('step')) return 'text-warning'
    return ''
  }

  return (
    <>
      <div className="checkout-order-summary">
        <div className="flex items-center gap-3">
          <span className={`badge checkout-state ${getStateClass(order.state)}`}>{display(order.state)}</span>
          {order.simulated && <span className="badge badge-neutral">SIMULATED</span>}
        </div>
        <strong className="text-2xl font-mono">{formatAmount(order)}</strong>
      </div>
      <div className="metric-grid small checkout-risk-grid">
        <article className="metric-card">
          <span className="metric-label">Risk score</span>
          <strong className="metric-value">{display(order.score)}</strong>
          <small className="text-text-dim">Server-provided</small>
        </article>
        <article className="metric-card">
          <span className="metric-label">Action</span>
          <strong className={`metric-value ${getActionClass(order.action)}`}>{display(order.action)}</strong>
          <small className="text-text-dim">Decision</small>
        </article>
        <article className="metric-card">
          <span className="metric-label">Step-up</span>
          <strong className={`metric-value ${needsStepUp(order) ? 'text-warning' : 'text-success'}`}>{needsStepUp(order) ? 'Required' : 'Not required'}</strong>
          <small className="text-text-dim">Verification</small>
        </article>
        <article className="metric-card">
          <span className="metric-label">Receipt</span>
          <strong className={`metric-value ${order.receiptAvailable ? 'text-success' : 'text-warning'}`}>{order.receiptAvailable ? 'Available' : 'Pending'}</strong>
          <small className="text-text-dim">Signed by server</small>
        </article>
      </div>
      <div className="checkout-identifiers">
        <OrderIdentifier label="Checkout order" value={order.id} />
        <OrderIdentifier label="PayPal order" value={order.paypalOrderId} />
        <OrderIdentifier label="PayPal authorization" value={order.paypalAuthorizationId} />
        <OrderIdentifier label="Capture" value={order.captureId} />
        <OrderIdentifier label="Scenario" value={order.scenarioId} />
      </div>
      <section className="checkout-reasons" aria-labelledby="reason-heading">
        <h4 id="reason-heading" className="text-lg font-semibold mb-4">Decision reasons</h4>
        {reasons.length === 0 ? (
          <p className="text-text-muted text-center py-4">No decision reasons have been provided.</p>
        ) : (
          reasons.map((reason, index) => (
            <article key={`${reason.code || 'reason'}-${index}`} className="card-hover p-4 border-l-3 border-primary">
              <div className="flex items-start justify-between gap-4 mb-2">
                <strong className="font-mono text-sm text-primary">{display(reason.code)}</strong>
                <span className="text-text-dim font-mono text-xs">
                  {display(reason.component)}
                  {reason.score !== null && reason.score !== undefined ? ` · score ${reason.score}` : ''}
                </span>
              </div>
              <p className="text-text-muted text-sm">{reason.message || 'No reason message provided.'}</p>
            </article>
          ))
        )}
      </section>
      <div className="checkout-timestamps flex flex-wrap gap-4 text-text-dim font-mono text-xs mt-4">
        <span><Clock className="w-3 h-3 inline mr-1" /> Created {formatDate(order.createdAt)}</span>
        <span><Clock className="w-3 h-3 inline mr-1" /> Updated {formatDate(order.updatedAt)}</span>
      </div>
    </>
  )
}

export default function CheckoutPage({ token }) {
  const [view, setView] = useState('checkout')
  const [form, setForm] = useState({ amount: '25.00', note: '' })
  const [order, setOrder] = useState(null)
  const [busy, setBusy] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState('')
  const [authorizationStarted, setAuthorizationStarted] = useState(false)
  const [stepUpOpen, setStepUpOpen] = useState(false)
  const [pollTarget, setPollTarget] = useState(null)
  const [polling, setPolling] = useState(false)
  const [pollNote, setPollNote] = useState('')
  const pollSequence = useRef(0)
  const { getTelemetry } = useSessionTelemetry()

  const queuePolling = useCallback(id => {
    pollSequence.current += 1
    setPollTarget({ id, sequence: pollSequence.current })
  }, [])

  const acceptNewOrder = useCallback(nextOrder => {
    setPollTarget(null)
    setPolling(false)
    setPollNote('')
    setError('')
    setOrder(nextOrder)
    setAuthorizationStarted(nextOrder?.state !== 'CREATED')
    setStepUpOpen(needsStepUp(nextOrder))
  }, [])

  const acceptAuthorization = useCallback(nextOrder => {
    setOrder(current => ({ ...nextOrder, demoOtp: nextOrder.demoOtp ?? current?.demoOtp ?? null }))
    setAuthorizationStarted(true)
    setError('')
    setStepUpOpen(needsStepUp(nextOrder))
    if (nextOrder?.id) queuePolling(nextOrder.id)
  }, [queuePolling])

  useEffect(() => {
    if (!pollTarget?.id) return undefined
    let active = true
    let timer
    let attempts = 0
    setPolling(true)
    setPollNote('Polling the server for the latest decision…')

    const check = async () => {
      try {
        const latest = await getCheckoutOrder(token, pollTarget.id)
        if (!active) return
        setOrder(current => ({ ...latest, demoOtp: latest.demoOtp ?? current?.demoOtp ?? null }))
        if (needsStepUp(latest)) {
          setStepUpOpen(true)
          setPolling(false)
          setPollNote('Server decision paused for step-up verification.')
          return
        }
        if (TERMINAL_STATES.has(latest?.state)) {
          setPolling(false)
          setPollNote(`Server reached terminal state ${latest.state}.`)
          return
        }
        attempts += 1
        if (attempts >= 10) {
          setPolling(false)
          setPollNote('Automatic polling paused. Use Refresh order to check for a later update.')
          return
        }
        timer = window.setTimeout(check, 1200)
      } catch (requestError) {
        if (!active) return
        setPolling(false)
        setPollNote('Automatic polling stopped after a request error.')
        setError(requestError.message || 'Unable to refresh the checkout decision.')
      }
    }

    timer = window.setTimeout(check, 1000)
    return () => {
      active = false
      window.clearTimeout(timer)
    }
  }, [token, pollTarget])

  const createOrder = async event => {
    event.preventDefault()
    setBusy(true)
    setError('')
    setOrder(null)
    setPollTarget(null)
    setPolling(false)
    setPollNote('')
    setStepUpOpen(false)
    setAuthorizationStarted(false)
    try {
      const created = await createCheckoutOrder(token, {
        amount: form.amount,
        note: form.note.trim(),
        telemetry: getTelemetry(),
      })
      acceptNewOrder(created)
    } catch (requestError) {
      setError(requestError.message || 'Unable to create the checkout order.')
    } finally {
      setBusy(false)
    }
  }

  const refreshOrder = async () => {
    if (!order?.id) return
    setRefreshing(true)
    setError('')
    try {
      const latest = await getCheckoutOrder(token, order.id)
      setOrder({ ...latest, demoOtp: latest.demoOtp ?? order.demoOtp ?? null })
      setStepUpOpen(needsStepUp(latest))
    } catch (requestError) {
      setError(requestError.message || 'Unable to refresh this order.')
    } finally {
      setRefreshing(false)
    }
  }

  const closeStepUp = useCallback(() => setStepUpOpen(false), [])
  const showPayPal = Boolean(order?.paypalOrderId && order?.state === 'CREATED' && !authorizationStarted && !needsStepUp(order))

  return (
    <div className="checkout-page">
      <div className="page-header">
        <div>
          <p className="eyebrow">CHIMERA CHECKOUT SHIELD</p>
          <h2 className="page-title">Authorization with a visible decision trail</h2>
          <p className="page-subtitle">Create orders on the server, approve with PayPal, and inspect risk decisions, step-up outcomes, and signed receipts.</p>
        </div>
        <span className="badge badge-info">BACKEND-AUTHORIZED FLOW</span>
      </div>

      <div className="tabs checkout-tabs flex gap-2 mb-6" role="tablist" aria-label="Checkout Shield views">
        <button type="button" role="tab" aria-selected={view === 'checkout'} className={`btn-secondary ${view === 'checkout' ? 'bg-primary/10 border-primary text-primary' : ''}`} onClick={() => setView('checkout')}>
          <CreditCard className="w-4 h-4 mr-2" />
          Manual checkout
        </button>
        <button type="button" role="tab" aria-selected={view === 'simulator'} className={`btn-secondary ${view === 'simulator' ? 'bg-primary/10 border-primary text-primary' : ''}`} onClick={() => setView('simulator')}>
          <Shield className="w-4 h-4 mr-2" />
          Scenario simulator
        </button>
        <button type="button" role="tab" aria-selected={view === 'analyst'} className={`btn-secondary ${view === 'analyst' ? 'bg-primary/10 border-primary text-primary' : ''}`} onClick={() => setView('analyst')}>
          <ExternalLink className="w-4 h-4 mr-2" />
          Analyst decisions
        </button>
      </div>

      {view === 'analyst' ? (
        <AnalystOrdersTable token={token} />
      ) : (
        <>
          {view === 'checkout' && (
            <section className="card mb-6" style={{ borderColor: 'var(--color-border)' }}>
              <div className="section-header">
                <div>
                  <p className="eyebrow">NEW SERVER ORDER</p>
                  <h3 className="section-title">Manual checkout</h3>
                </div>
              </div>
              <form onSubmit={createOrder} className="space-y-4">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="md:col-span-2">
                    <label className="label">Note</label>
                    <input
                      required
                      value={form.note}
                      onChange={event => setForm({ ...form, note: event.target.value })}
                      placeholder="Checkout reference or purchase note"
                      maxLength={240}
                      className="input"
                    />
                  </div>
                  <div>
                    <label className="label">Amount (USD)</label>
                    <input
                      required
                      type="number"
                      min="0.01"
                      step="0.01"
                      inputMode="decimal"
                      value={form.amount}
                      onChange={event => setForm({ ...form, amount: event.target.value })}
                      className="input"
                    />
                  </div>
                </div>
                <div className="flex items-center justify-between p-3 rounded-lg bg-surface/50 border border-border/50">
                  <div className="flex items-center gap-2">
                    <span className="text-text-dim">Purpose</span>
                    <strong className="font-mono text-primary">CHECKOUT</strong>
                  </div>
                  <small className="text-text-dim">Currency fixed to USD</small>
                </div>
                <button className="btn-primary w-full" disabled={busy}>
                  {busy ? (
                    <>
                      <svg className="animate-spin h-5 w-5 mr-2" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" /></svg>
                      Creating server order…
                    </>
                  ) : 'Create checkout order'}
                </button>
              </form>
              <div className="mt-4 p-4 rounded-lg bg-surface/50 border border-border/50">
                <strong className="text-primary font-mono text-sm">Telemetry and model scope</strong>
                <p className="text-text-muted text-sm mt-2">
                  Only bounded keystroke intervals and pointer movements are sent; raw key contents are never collected. 
                  If no server scoring model is configured for manual checkout, this telemetry is integration data only and the score may be unavailable. 
                  This browser does not perform or claim real card scoring.
                </p>
              </div>
            </section>
          )}

          {view === 'simulator' && <ScenarioCards token={token} onOrder={acceptNewOrder} />}

          {error && (
            <div className="card mb-6 border-danger/50 bg-danger-bg/30" role="alert">
              <div className="flex items-start gap-3">
                <AlertCircle className="w-5 h-5 text-danger flex-shrink-0" />
                <div>
                  <strong>Checkout request failed</strong>
                  <span className="text-text-muted ml-2">{error}</span>
                </div>
              </div>
            </div>
          )}

          <section className="card checkout-order-card" aria-live="polite">
            <div className="section-header">
              <div>
                <p className="eyebrow">CURRENT ORDER</p>
                <h3 className="section-title">Server decision and payment</h3>
              </div>
              {order?.id && (
                <button type="button" className="btn-secondary" onClick={refreshOrder} disabled={refreshing}>
                  <RefreshCw className={`w-4 h-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
                  {refreshing ? 'Refreshing…' : 'Refresh order'}
                </button>
              )}
            </div>
            {!order ? (
              <div className="card-hover p-8 text-center border-dashed border-border">
                <CreditCard className="w-12 h-12 text-text-dim mx-auto mb-4" />
                <p className="text-text-muted">{view === 'simulator' ? 'Run a simulated scenario to create a payment order or a terminal blocked attempt.' : 'Create an order to load its backend-provided PayPal order ID.'}</p>
              </div>
            ) : (
              <>
                <OrderDetails order={order} />
                {order.state === 'BLOCKED' && (
                  <div className="card-hover mt-4 p-4 border-danger/50 bg-danger-bg/30">
                    <div className="flex items-start gap-3">
                      <AlertCircle className="w-5 h-5 text-danger flex-shrink-0" />
                      <div>
                        <strong className="text-danger">Blocked before payment</strong>
                        <p className="text-text-muted mt-1">The server returned a terminal BLOCKED decision. No PayPal interaction is required or offered.</p>
                      </div>
                    </div>
                  </div>
                )}
                {needsStepUp(order) && !stepUpOpen && (
                  <button type="button" className="btn-primary w-full mt-4" onClick={() => setStepUpOpen(true)}>
                    <Shield className="w-4 h-4 mr-2" />
                    Open step-up verification
                  </button>
                )}
                {showPayPal ? (
                  <div className="checkout-payment mt-6">
                    <div>
                      <strong className="block mb-1">Approve this server-created order</strong>
                      <p className="text-text-muted text-sm">PayPal supplies the approval callback. Checkout Shield performs authorization through the backend; this browser never creates or captures a PayPal order directly.</p>
                    </div>
                    <PayPalCheckoutButton token={token} order={order} getTelemetry={getTelemetry} onOrder={acceptAuthorization} onError={setError} disabled={polling} />
                  </div>
                ) : order.state === 'CREATED' && !order.paypalOrderId ? (
                  <p className="error mt-4">The order is ready, but the backend did not provide a PayPal order ID.</p>
                ) : null}
                {(polling || pollNote) && (
                  <div className="flex items-center gap-2 mt-4 text-text-muted text-sm">
                    {polling && <span className="w-2 h-2 rounded-full bg-primary animate-pulse-soft" />}
                    <span>{pollNote}</span>
                  </div>
                )}
                <ReceiptView token={token} orderId={order.id} available={Boolean(order.receiptAvailable)} />
              </>
            )}
          </section>
        </>
      )}

      {stepUpOpen && order && (
        <StepUpDialog token={token} order={order} getTelemetry={getTelemetry} onVerified={acceptAuthorization} onClose={closeStepUp} />
      )}
    </div>
  )
}