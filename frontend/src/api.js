async function request(method, url, body) {
  const json = body && !(body instanceof FormData)
  const res = await fetch(url, {
    method,
    body: json ? JSON.stringify(body) : body,
    headers: json ? { 'Content-Type': 'application/json' } : undefined,
  })
  if (!res.ok) {
    let detail = `${res.status}`
    try { detail = (await res.json()).detail || detail } catch { /* 非 JSON 响应 */ }
    throw new Error(detail)
  }
  return res.status === 204 ? null : res.json()
}

export const api = {
  books: () => request('GET', '/api/books'),
  book: (id) => request('GET', `/api/books/${id}`),
  rules: () => request('GET', '/api/rules'),
  upload(file) {
    const fd = new FormData()
    fd.append('file', file)
    return request('POST', '/api/books', fd)
  },
  fix: (id, mode = 'basic') => request('POST', `/api/books/${id}/fix?mode=${mode}`),
  remove: (id) => request('DELETE', `/api/books/${id}`),
  addWaiver: (id, waiver) => request('POST', `/api/books/${id}/waivers`, waiver),
  removeWaiver: (id, wid) => request('DELETE', `/api/books/${id}/waivers/${wid}`),
  downloadUrl: (id, which = 'fixed') => `/api/books/${id}/download?which=${which}`,
}

export const STATUS = {
  queued: '排队中',
  auditing: '体检中',
  ready: '已体检',
  fixing: '修复中',
  fixed: '已修复',
  error: '出错',
}

export const BUSY = new Set(['queued', 'auditing', 'fixing'])
