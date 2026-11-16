import { useCallback, useEffect, useRef } from 'react'

const MAX_KEYSTROKE_INTERVALS = 64
const MAX_MOUSE_MOVEMENTS = 120

function appendBounded(list, value, limit) {
  list.push(value)
  if (list.length > limit) list.splice(0, list.length - limit)
}

export default function useSessionTelemetry() {
  const data = useRef({ keystrokeIntervalsMs: [], keystrokeDwellMs: [], mouseMovements: [] })
  const previousKeyTime = useRef(null)
  const activeKeyDown = useRef(null)
  const previousMouse = useRef(null)

  useEffect(() => {
    const onKeyDown = event => {
      if (event.repeat) return
      const now = performance.now()
      activeKeyDown.current = now
      if (previousKeyTime.current !== null) {
        appendBounded(
          data.current.keystrokeIntervalsMs,
          Math.max(0, Math.round(now - previousKeyTime.current)),
          MAX_KEYSTROKE_INTERVALS,
        )
      }
      previousKeyTime.current = now
    }

    const onKeyUp = () => {
      if (activeKeyDown.current === null) return
      appendBounded(
        data.current.keystrokeDwellMs,
        Math.min(60_000, Math.max(0, Math.round(performance.now() - activeKeyDown.current))),
        MAX_KEYSTROKE_INTERVALS,
      )
      activeKeyDown.current = null
    }

    const onMouseMove = event => {
      const now = performance.now()
      const previous = previousMouse.current
      if (previous) {
        appendBounded(data.current.mouseMovements, {
          dx: Math.round(event.clientX - previous.x),
          dy: Math.round(event.clientY - previous.y),
          dtMs: Math.min(60_000, Math.max(0, Math.round(now - previous.time))),
        }, MAX_MOUSE_MOVEMENTS)
      }
      previousMouse.current = { x: event.clientX, y: event.clientY, time: now }
    }

    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('keyup', onKeyUp)
    window.addEventListener('mousemove', onMouseMove, { passive: true })
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('keyup', onKeyUp)
      window.removeEventListener('mousemove', onMouseMove)
    }
  }, [])

  const getTelemetry = useCallback(() => ({
    keystrokeIntervalsMs: [...data.current.keystrokeIntervalsMs],
    keystrokeDwellMs: [...data.current.keystrokeDwellMs],
    mouseMovements: data.current.mouseMovements.map(movement => ({ ...movement })),
  }), [])

  const resetTelemetry = useCallback(() => {
    data.current = { keystrokeIntervalsMs: [], keystrokeDwellMs: [], mouseMovements: [] }
    previousKeyTime.current = null
    activeKeyDown.current = null
    previousMouse.current = null
  }, [])

  return { getTelemetry, resetTelemetry }
}
