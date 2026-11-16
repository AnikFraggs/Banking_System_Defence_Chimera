const configuredApi = import.meta.env.VITE_API_URL || 'http://localhost:8080'
const API = configuredApi === '/api' ? '' : configuredApi.replace(/\/$/, '')

async function request(path, { token, method = 'GET', body } = {}) {
  const headers = { Authorization: `Bearer ${token}` }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  const response = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  const payload = response.status === 204 ? null : await response.json().catch(() => null)

  if (!response.ok) {
    const detail = payload?.detail || payload?.message || payload?.error
    throw new Error(detail || `Request failed (${response.status})`)
  }
  return payload
}

const orderPath = id => `/api/checkout/orders/${encodeURIComponent(id)}`

export function createCheckoutOrder(token, { amount, note, scenarioId, telemetry }) {
  return request('/api/checkout/orders', {
    token,
    method: 'POST',
    body: {
      amount,
      currency: 'USD',
      note,
      purpose: 'CHECKOUT',
      ...(scenarioId ? { scenarioId } : {}),
      telemetry,
    },
  })
}

export function authorizeCheckoutOrder(token, id, telemetry) {
  return request(`${orderPath(id)}/authorize`, {
    token,
    method: 'POST',
    body: { telemetry },
  })
}

export function getCheckoutOrder(token, id) {
  return request(orderPath(id), { token })
}

export function verifyCheckoutStepUp(token, id, code, telemetry) {
  return request(`${orderPath(id)}/step-up/verify`, {
    token,
    method: 'POST',
    body: { code, telemetry },
  })
}

export function listScenarios(token) {
  return request('/api/scenarios', { token })
}

export function startSimulatorSession(token, scenarioId) {
  return request('/api/simulator/sessions', {
    token,
    method: 'POST',
    body: { scenarioId },
  })
}

export function listAnalystOrders(token) {
  return request('/api/analyst/orders', { token })
}

export function listAnalystCases(token) {
  return request('/api/analyst/cases', { token })
}

export function submitAnalystVerdict(token, caseId, verdict) {
  return request(`/api/analyst/cases/${encodeURIComponent(caseId)}/verdict`, {
    token,
    method: 'POST',
    body: { verdict },
  })
}

export function getSignedReceipt(token, orderId) {
  return request(`/api/receipts/${encodeURIComponent(orderId)}`, { token })
}
