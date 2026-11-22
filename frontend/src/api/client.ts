/**
 * Небольшой API-клиент: fetch-обёртка с JSON и единой обработкой ошибок.
 *
 * Backend отвечает ошибками в формате:
 *   { "error": { "code": "...", "message": "...", "details": ... } }
 * Любая неудача (сеть, таймаут, не-2xx, некорректный JSON) превращается в ApiError.
 */

/** Базовый путь API. В dev-режиме /api проксируется Vite на backend. */
export const API_BASE = '/api'

const DEFAULT_TIMEOUT_MS = 15_000

export interface ApiErrorBody {
  code: string
  message: string
  details?: unknown
}

export class ApiError extends Error {
  /** HTTP-статус; 0 — запрос не дошёл до сервера (нет сети, таймаут, отмена). */
  readonly status: number
  readonly code: string
  readonly details?: unknown

  constructor(status: number, body: ApiErrorBody) {
    super(body.message)
    this.name = 'ApiError'
    this.status = status
    this.code = body.code
    this.details = body.details
  }

  /** Сервер недоступен (сеть, таймаут) — в отличие от ошибки, которую вернул сам сервер. */
  get isNetworkError(): boolean {
    return this.status === 0
  }
}

type QueryValue = string | number | boolean | null | undefined

export interface RequestOptions extends Omit<RequestInit, 'body'> {
  /** Тело запроса — сериализуется в JSON. */
  json?: unknown
  /** Параметры строки запроса; null/undefined пропускаются. */
  query?: Record<string, QueryValue>
  /** Таймаут в миллисекундах (по умолчанию 15 с). */
  timeoutMs?: number
}

function buildUrl(path: string, query?: Record<string, QueryValue>): string {
  const url = path.startsWith('/') ? `${API_BASE}${path}` : `${API_BASE}/${path}`
  if (!query) return url
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value !== null && value !== undefined) params.append(key, String(value))
  }
  const qs = params.toString()
  return qs ? `${url}?${qs}` : url
}

function isErrorEnvelope(data: unknown): data is { error: ApiErrorBody } {
  if (typeof data !== 'object' || data === null || !('error' in data)) return false
  const err = (data as { error: unknown }).error
  return (
    typeof err === 'object' &&
    err !== null &&
    typeof (err as ApiErrorBody).code === 'string' &&
    typeof (err as ApiErrorBody).message === 'string'
  )
}

async function readBody(response: Response): Promise<unknown> {
  if (response.status === 204) return undefined
  const text = await response.text()
  if (!text) return undefined
  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('json')) return text
  try {
    return JSON.parse(text)
  } catch {
    // Для ответа с ошибкой отдаём текст как есть — его разберёт apiRequest.
    if (!response.ok) return text
    throw new ApiError(response.status, {
      code: 'invalid_json',
      message: 'Сервер вернул некорректный ответ',
    })
  }
}

/**
 * Выполняет запрос к API и возвращает разобранный JSON.
 * @example const data = await apiRequest<Health>('/health')
 */
export async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { json, query, timeoutMs = DEFAULT_TIMEOUT_MS, headers, signal, ...init } = options

  const requestHeaders = new Headers(headers)
  requestHeaders.set('Accept', 'application/json')
  if (json !== undefined) requestHeaders.set('Content-Type', 'application/json')

  // Таймаут + внешняя отмена (например, при уходе со страницы).
  const timeoutSignal = AbortSignal.timeout(timeoutMs)
  const combinedSignal = signal ? AbortSignal.any([signal, timeoutSignal]) : timeoutSignal

  let response: Response
  try {
    response = await fetch(buildUrl(path, query), {
      credentials: 'same-origin',
      ...init,
      headers: requestHeaders,
      body: json !== undefined ? JSON.stringify(json) : undefined,
      signal: combinedSignal,
    })
  } catch (cause) {
    const timedOut = timeoutSignal.aborted
    const aborted = !timedOut && signal?.aborted
    throw new ApiError(0, {
      code: timedOut ? 'timeout' : aborted ? 'aborted' : 'network_error',
      message: timedOut
        ? 'Сервер не ответил вовремя'
        : aborted
          ? 'Запрос отменён'
          : 'Нет связи с сервером',
      details: cause instanceof Error ? cause.message : undefined,
    })
  }

  const data = await readBody(response)

  if (!response.ok) {
    if (isErrorEnvelope(data)) throw new ApiError(response.status, data.error)
    throw new ApiError(response.status, {
      code: `http_${response.status}`,
      message: response.status >= 500 ? 'Ошибка на сервере' : 'Ошибка запроса',
      details: data,
    })
  }

  return data as T
}

/** Короткие помощники для типичных методов. */
export const api = {
  get: <T>(path: string, options?: RequestOptions) =>
    apiRequest<T>(path, { ...options, method: 'GET' }),
  post: <T>(path: string, json?: unknown, options?: RequestOptions) =>
    apiRequest<T>(path, { ...options, method: 'POST', json }),
  put: <T>(path: string, json?: unknown, options?: RequestOptions) =>
    apiRequest<T>(path, { ...options, method: 'PUT', json }),
  patch: <T>(path: string, json?: unknown, options?: RequestOptions) =>
    apiRequest<T>(path, { ...options, method: 'PATCH', json }),
  delete: <T>(path: string, options?: RequestOptions) =>
    apiRequest<T>(path, { ...options, method: 'DELETE' }),
}

/** Ответ GET /api/health. */
export interface HealthResponse {
  status: string
  db: boolean
}

export const getHealth = (signal?: AbortSignal) => api.get<HealthResponse>('/health', { signal })
