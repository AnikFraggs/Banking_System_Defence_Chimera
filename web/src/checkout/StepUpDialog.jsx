import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import { verifyCheckoutStepUp } from './api'

export default function StepUpDialog({ token, order, getTelemetry, onVerified, onClose }) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const onKeyDown = event => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [busy, onClose])

  const submit = async event => {
    event.preventDefault()
    if (!code.trim()) return
    setBusy(true)
    setError('')
    try {
      const updated = await verifyCheckoutStepUp(token, order.id, code.trim(), getTelemetry())
      onVerified(updated)
      setCode('')
    } catch (requestError) {
      setError(requestError.message || 'Step-up verification failed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="step-up-dialog" role="presentation" onMouseDown={event => {
      if (event.target === event.currentTarget && !busy) onClose()
    }}>
      <section className="step-up-dialog-content" role="dialog" aria-modal="true" aria-labelledby="step-up-title">
        <div className="checkout-dialog-heading">
          <div>
            <p className="eyebrow">ADDITIONAL VERIFICATION</p>
            <h3 id="step-up-title">Simulated step-up verification</h3>
          </div>
          <button type="button" className="checkout-dialog-close" onClick={onClose} disabled={busy} aria-label="Close verification dialog">
            <X className="w-5 h-5" />
          </button>
        </div>
        <p className="text-text-muted mb-4">The server requires an additional verification step before it can continue this checkout.</p>
        {order?.demoOtp !== null && order?.demoOtp !== undefined && order?.demoOtp !== '' && (
          <div className="checkout-demo-otp mb-4">
            <span>Simulated verification only</span>
            <strong>Backend demo OTP: {order.demoOtp}</strong>
            <small>This code is supplied by the demo backend and is not a real authentication factor.</small>
          </div>
        )}
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="label">Verification code</label>
            <input
              autoFocus
              required
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={event => setCode(event.target.value)}
              placeholder="Enter verification code"
              disabled={busy}
              maxLength={6}
              pattern="[0-9]{6}"
              className="input text-center text-xl tracking-widest font-mono"
            />
          </div>
          {error && <p className="error text-sm" role="alert">{error}</p>}
          <button className="btn-primary w-full" disabled={busy || !code.trim()}>
            {busy ? 'Verifying…' : 'Verify and continue'}
          </button>
        </form>
      </section>
    </div>
  )
}