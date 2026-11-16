import { useCallback, useEffect, useState } from 'react'
import { getSignedReceipt } from '../api'

export default function ReceiptView({ token, orderId, available }) {
  const [receipt, setReceipt] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    if (!available || !orderId) return
    setLoading(true)
    setError('')
    try {
      setReceipt(await getSignedReceipt(token, orderId))
    } catch (requestError) {
      setReceipt(null)
      setError(requestError.message || 'The signed receipt is not available yet.')
    } finally {
      setLoading(false)
    }
  }, [token, orderId, available])

  useEffect(() => {
    setReceipt(null)
    setError('')
    load()
  }, [load])

  if (!available) return null

  return <section className="checkout-receipt" aria-labelledby="receipt-heading">
    <div className="checkout-section-heading">
      <div>
        <p className="eyebrow">SERVER-ISSUED RECEIPT</p>
        <h4 id="receipt-heading">Signed receipt</h4>
      </div>
      <button type="button" className="secondary" onClick={load} disabled={loading}>{loading ? 'Loading…' : 'Reload receipt'}</button>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    {receipt ? <dl className="checkout-receipt-fields">
      <div><dt>Payload</dt><dd><pre>{typeof receipt.payload === 'string' ? receipt.payload : JSON.stringify(receipt.payload ?? null, null, 2)}</pre></dd></div>
      <div><dt>Signature</dt><dd><code>{receipt.signature || 'Not provided'}</code></dd></div>
      <div><dt>Key version</dt><dd><code>{receipt.keyVersion || 'Not provided'}</code></dd></div>
    </dl> : !loading && !error ? <p className="muted">No receipt data returned.</p> : null}
  </section>
}
