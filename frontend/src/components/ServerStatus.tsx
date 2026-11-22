import { useEffect, useState } from 'react'
import { getHealth } from '../api/client'

type Status = 'checking' | 'ok' | 'no-db' | 'down'

const POLL_INTERVAL_MS = 60_000

const labels: Record<Status, string> = {
  checking: 'Проверяем связь с сервером…',
  ok: 'Сервер доступен',
  'no-db': 'Сервер доступен, база данных — нет',
  down: 'Сервер недоступен',
}

/** Ненавязчивый индикатор связи с backend: опрашивает GET /api/health. */
export function ServerStatus() {
  const [status, setStatus] = useState<Status>('checking')

  useEffect(() => {
    let controller: AbortController | null = null

    const check = async () => {
      controller?.abort()
      const current = new AbortController()
      controller = current
      try {
        const health = await getHealth(current.signal)
        if (current.signal.aborted) return
        setStatus(health.status === 'ok' && health.db ? 'ok' : health.status === 'ok' ? 'no-db' : 'down')
      } catch {
        if (!current.signal.aborted) setStatus('down')
      }
    }

    void check()
    const timer = window.setInterval(() => void check(), POLL_INTERVAL_MS)
    const onOnline = () => void check()
    window.addEventListener('online', onOnline)

    return () => {
      window.clearInterval(timer)
      window.removeEventListener('online', onOnline)
      controller?.abort()
    }
  }, [])

  return (
    <p className={`server-status server-status--${status}`} role="status" aria-live="polite">
      <span className="server-status__dot" aria-hidden="true" />
      {labels[status]}
    </p>
  )
}
