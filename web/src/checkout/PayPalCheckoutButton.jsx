import { useEffect, useRef, useState } from 'react'
import { authorizeCheckoutOrder } from './api'

const STUB_MODE = String(import.meta.env.VITE_PAYPAL_STUB).toLowerCase() === 'true'
let sdkPromise

function loadPayPalSdk() {
  if (window.paypal?.Buttons) return Promise.resolve(window.paypal)
  if (sdkPromise) return sdkPromise

  const clientId = import.meta.env.VITE_PAYPAL_CLIENT_ID
  const configuredUrl = import.meta.env.VITE_PAYPAL_SDK_URL
  if (!clientId && !configuredUrl) {
    return Promise.reject(new Error('Set VITE_PAYPAL_CLIENT_ID, or enable explicit stub mode with VITE_PAYPAL_STUB=true.'))
  }

  const sdkUrl = configuredUrl || `https://www.paypal.com/sdk/js?client-id=${encodeURIComponent(clientId)}&currency=USD&intent=authorize&components=buttons`

  sdkPromise = new Promise((resolve, reject) => {
    const existing = document.querySelector('script[data-chimera-paypal-sdk]')
    const script = existing || document.createElement('script')
    if (!existing) {
      script.src = sdkUrl
      script.async = true
      script.dataset.chimeraPaypalSdk = 'true'
    }

    const cleanup = () => {
      script.removeEventListener('load', onLoad)
      script.removeEventListener('error', onError)
    }
    const onLoad = () => {
      cleanup()
      if (window.paypal?.Buttons) resolve(window.paypal)
      else {
        sdkPromise = null
        reject(new Error('PayPal SDK loaded without a Buttons component.'))
      }
    }
    const onError = () => {
      cleanup()
      sdkPromise = null
      script.remove()
      reject(new Error('Unable to load PayPal. Check the SDK configuration and network connection.'))
    }

    script.addEventListener('load', onLoad)
    script.addEventListener('error', onError)
    if (!existing) document.head.appendChild(script)
  })

  return sdkPromise
}

export default function PayPalCheckoutButton({ token, order, getTelemetry, onOrder, onError, disabled = false }) {
  const containerRef = useRef(null)
  const busyRef = useRef(false)
  const disabledRef = useRef(disabled)
  disabledRef.current = disabled
  const callbacksRef = useRef({ getTelemetry, onOrder, onError })
  callbacksRef.current = { getTelemetry, onOrder, onError }
  const [loading, setLoading] = useState(!STUB_MODE)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (STUB_MODE) return undefined
    let active = true
    let buttons
    setLoading(true)
    setError('')
    setMessage('')

    loadPayPalSdk().then(paypal => {
      if (!active || !containerRef.current) return
      containerRef.current.innerHTML = ''
      buttons = paypal.Buttons({
        style: { layout: 'vertical', shape: 'rect', label: 'paypal', color: 'gold' },
        createOrder: () => {
          if (busyRef.current || disabledRef.current) throw new Error('Checkout authorization is already in progress.')
          if (!order?.paypalOrderId) throw new Error('The backend did not provide a PayPal order ID.')
          return order.paypalOrderId
        },
        onApprove: async () => {
          if (busyRef.current) return
          busyRef.current = true
          setBusy(true)
          setError('')
          setMessage('Authorizing with Checkout Shield…')
          try {
            const updated = await authorizeCheckoutOrder(token, order.id, callbacksRef.current.getTelemetry())
            callbacksRef.current.onOrder(updated)
            setMessage('PayPal approval submitted. Waiting for the server decision.')
          } catch (requestError) {
            const text = requestError.message || 'Authorization failed.'
            setError(text)
            callbacksRef.current.onError?.(text)
          } finally {
            busyRef.current = false
            setBusy(false)
          }
        },
        onCancel: () => setMessage('PayPal approval was cancelled. You can retry when ready.'),
        onError: sdkError => {
          const text = sdkError?.message || 'PayPal could not complete this approval.'
          setError(text)
          callbacksRef.current.onError?.(text)
        },
      })
      return buttons.render(containerRef.current)
    }).then(() => {
      if (active) setLoading(false)
    }).catch(sdkError => {
      if (!active) return
      setLoading(false)
      setError(sdkError.message || 'Unable to initialize PayPal.')
    })

    return () => {
      active = false
      if (containerRef.current) containerRef.current.innerHTML = ''
    }
  }, [token, order?.id, order?.paypalOrderId])

  const authorizeStub = async () => {
    if (busyRef.current || disabled) return
    busyRef.current = true
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const updated = await authorizeCheckoutOrder(token, order.id, getTelemetry())
      onOrder(updated)
    } catch (requestError) {
      const text = requestError.message || 'Simulated authorization failed.'
      setError(text)
      onError?.(text)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  if (STUB_MODE) {
    return (
      <div className="checkout-paypal">
        <button
          type="button"
          className="btn-primary w-full checkout-stub-button"
          onClick={authorizeStub}
          disabled={disabled || busy}
        >
          {busy ? (
            <>
              <svg className="animate-spin h-5 w-5 mr-2" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" /></svg>
              Submitting simulated approval…
            </>
          ) : 'Simulated PayPal approval'}
        </button>
        <p className="text-text-muted text-sm text-center mt-3">Stub mode is explicit. No PayPal SDK is loaded and no real PayPal approval occurs.</p>
        {error && <p className="error text-center mt-3" role="alert">{error}</p>}
      </div>
    )
  }

  return (
    <div className="checkout-paypal">
      {loading && <p className="text-text-muted text-center checkout-inline-status">Loading secure PayPal buttons…</p>}
      <div ref={containerRef} className={disabled || busy ? 'checkout-paypal-disabled' : ''} aria-disabled={disabled || busy} />
      {message && <p className="text-text-muted text-center checkout-inline-status" role="status">{message}</p>}
      {error && <p className="error text-center mt-3" role="alert">{error}</p>}
    </div>
  )
}