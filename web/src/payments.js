// Payment method launchers. No real money moves — these open the real provider
// surfaces (Razorpay checkout in test mode, Google Pay) or a working dummy card
// modal, then resolve with a reference the backend records against the request.

function loadScript(src) {
  return new Promise((resolve, reject) => {
    if (document.querySelector(`script[src="${src}"]`)) return resolve(true)
    const s = document.createElement('script')
    s.src = src
    s.onload = () => resolve(true)
    s.onerror = () => reject(new Error(`Failed to load ${src}`))
    document.body.appendChild(s)
  })
}

// Razorpay test checkout. Uses the public test key so the real Razorpay widget
// opens; test cards (e.g. 4111 1111 1111 1111) complete without real charges.
export async function payWithRazorpay({ amount, name }) {
  await loadScript('https://checkout.razorpay.com/v1/checkout.js')
  return new Promise((resolve, reject) => {
    const rzp = new window.Razorpay({
      key: 'rzp_test_1DP5mmOlF5G5ag', // Razorpay public test key
      amount: Math.round(Number(amount) * 100),
      currency: 'INR',
      name: 'CHIMERA Bank',
      description: `Payment for ${name || 'service request'}`,
      handler: (response) => resolve({ method: 'RAZORPAY', reference: response.razorpay_payment_id || 'rzp_test_ok' }),
      prefill: { name: name || 'Client' },
      theme: { color: '#63dfcc' },
      modal: { ondismiss: () => reject(new Error('Razorpay checkout closed')) },
    })
    rzp.open()
  })
}

// Opens Google Pay. Uses the Google Pay JS API test environment when available;
// otherwise falls back to opening pay.google.com in a new tab.
export async function payWithGooglePay({ amount }) {
  try {
    await loadScript('https://pay.google.com/gp/p/js/pay.js')
    const client = new window.google.payments.api.PaymentsClient({ environment: 'TEST' })
    const request = {
      apiVersion: 2, apiVersionMinor: 0,
      allowedPaymentMethods: [{
        type: 'CARD',
        parameters: { allowedAuthMethods: ['PAN_ONLY', 'CRYPTOGRAM_3DS'], allowedCardNetworks: ['VISA', 'MASTERCARD'] },
        tokenizationSpecification: { type: 'PAYMENT_GATEWAY', parameters: { gateway: 'example', gatewayMerchantId: 'exampleMerchantId' } },
      }],
      merchantInfo: { merchantName: 'CHIMERA Bank' },
      transactionInfo: { totalPriceStatus: 'FINAL', totalPrice: String(Number(amount).toFixed(2)), currencyCode: 'INR', countryCode: 'IN' },
    }
    const paymentData = await client.loadPaymentData(request)
    return { method: 'GPAY', reference: 'gpay_' + (paymentData?.paymentMethodData?.type || 'test') }
  } catch (e) {
    // Test env often can't complete without a real merchant; open Google Pay site as a graceful fallback.
    window.open('https://pay.google.com', '_blank', 'noopener')
    return { method: 'GPAY', reference: 'gpay_redirect' }
  }
}

// Dummy card modal for credit / debit card. Opens a real, working overlay that
// collects card details and validates them client-side. No charge is made.
export function payWithCard({ amount, kind }) {
  return new Promise((resolve, reject) => {
    const overlay = document.createElement('div')
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(4,15,25,.8);display:flex;align-items:center;justify-content:center;z-index:9999'
    overlay.innerHTML = `
      <form style="background:#0d2439;border:1px solid #1f4257;border-radius:14px;padding:24px;width:340px;color:#eaf3fb;font-family:inherit">
        <h3 style="margin:0 0 4px">${kind === 'DEBIT_CARD' ? 'Debit' : 'Credit'} Card</h3>
        <p style="color:#95aebf;font-size:.85rem;margin:0 0 16px">Dummy checkout · ₹${Number(amount).toFixed(2)} · no real charge</p>
        <label style="display:block;font-size:.75rem;color:#b9cad7">Card number
          <input name="num" inputmode="numeric" placeholder="4111 1111 1111 1111" required maxlength="19"
            style="width:100%;margin-top:4px;padding:9px;border-radius:8px;border:1px solid #30566e;background:#08283a;color:#fff"/></label>
        <div style="display:flex;gap:10px;margin-top:10px">
          <label style="flex:1;font-size:.75rem;color:#b9cad7">Expiry
            <input name="exp" placeholder="MM/YY" required maxlength="5"
              style="width:100%;margin-top:4px;padding:9px;border-radius:8px;border:1px solid #30566e;background:#08283a;color:#fff"/></label>
          <label style="width:90px;font-size:.75rem;color:#b9cad7">CVV
            <input name="cvv" inputmode="numeric" placeholder="123" required maxlength="4" type="password"
              style="width:100%;margin-top:4px;padding:9px;border-radius:8px;border:1px solid #30566e;background:#08283a;color:#fff"/></label>
        </div>
        <div style="display:flex;gap:10px;margin-top:18px">
          <button type="button" data-cancel style="flex:1;padding:10px;border-radius:8px;border:1px solid #30566e;background:transparent;color:#b9cad7;cursor:pointer">Cancel</button>
          <button type="submit" style="flex:2;padding:10px;border-radius:8px;border:none;background:#63dfcc;color:#022;cursor:pointer;font-weight:700">Pay ₹${Number(amount).toFixed(2)}</button>
        </div>
      </form>`
    const close = () => document.body.removeChild(overlay)
    overlay.querySelector('[data-cancel]').onclick = () => { close(); reject(new Error('Card payment cancelled')) }
    overlay.querySelector('form').onsubmit = (e) => {
      e.preventDefault()
      const num = e.target.num.value.replace(/\s+/g, '')
      if (!/^\d{15,16}$/.test(num)) { alert('Enter a valid 15–16 digit card number.'); return }
      if (!/^\d{2}\/\d{2}$/.test(e.target.exp.value)) { alert('Enter expiry as MM/YY.'); return }
      if (!/^\d{3,4}$/.test(e.target.cvv.value)) { alert('Enter a valid CVV.'); return }
      close()
      resolve({ method: kind, reference: kind.toLowerCase() + '_' + num.slice(-4) })
    }
    document.body.appendChild(overlay)
  })
}

export async function runPayment(method, ctx) {
  switch (method) {
    case 'RAZORPAY': return payWithRazorpay(ctx)
    case 'GPAY': return payWithGooglePay(ctx)
    case 'CREDIT_CARD': return payWithCard({ ...ctx, kind: 'CREDIT_CARD' })
    case 'DEBIT_CARD': return payWithCard({ ...ctx, kind: 'DEBIT_CARD' })
    default: return { method: 'NETBANKING', reference: 'netbanking_ok' }
  }
}
