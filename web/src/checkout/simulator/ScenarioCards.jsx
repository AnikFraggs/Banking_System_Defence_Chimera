import { useCallback, useEffect, useState } from 'react'
import { listScenarios, startSimulatorSession } from '../api'

export default function ScenarioCards({ token, onOrder }) {
  const [scenarios, setScenarios] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const result = await listScenarios(token)
      setScenarios(Array.isArray(result) ? result : [])
    } catch (requestError) {
      setError(requestError.message || 'Unable to load scenarios.')
    } finally {
      setLoading(false)
    }
  }, [token])

  useEffect(() => { load() }, [load])

  const start = async scenarioId => {
    setBusyId(scenarioId)
    setError('')
    try {
      const result = await startSimulatorSession(token, scenarioId)
      onOrder(result)
    } catch (requestError) {
      setError(requestError.message || 'Unable to start this simulated session.')
    } finally {
      setBusyId(null)
    }
  }

  return <section className="checkout-scenarios" aria-labelledby="scenario-heading">
    <div className="page-heading compact">
      <div>
        <p className="eyebrow">CONTROLLED TEST CASES</p>
        <h3 id="scenario-heading">Scenario simulator</h3>
        <p className="muted">Each scenario is simulated. Blocked scenarios terminate on the server without PayPal interaction; payment scenarios continue through the same authorization flow.</p>
      </div>
      <button type="button" className="secondary" onClick={load} disabled={loading}>Refresh scenarios</button>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    {loading ? <div className="card loading">Loading simulated scenarios…</div> : <div className="checkout-scenario-grid">
      {scenarios.length === 0 && <div className="card"><p className="muted">No simulated scenarios are available.</p></div>}
      {scenarios.map(scenario => <article className="card checkout-scenario-card" key={scenario.id}>
        <span className="pill">SIMULATED</span>
        <h4>{scenario.title || scenario.id || 'Untitled scenario'}</h4>
        <p>{scenario.description || 'No scenario description provided.'}</p>
        <button type="button" className="secondary" onClick={() => start(scenario.id)} disabled={busyId !== null || !scenario.id}>
          {busyId === scenario.id ? 'Starting simulation…' : 'Run simulated scenario'}
        </button>
      </article>)}
    </div>}
  </section>
}
