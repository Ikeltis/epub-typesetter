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
  board: (id) => request('GET', `/api/books/${id}/board`),
  optionsSchema: () => request('GET', '/api/options'),
  saveOptions: (id, o) => request('PUT', `/api/books/${id}/options`, o),
  spine: (id, which) => request('GET', `/api/books/${id}/spine/${which}`),
  saveDecisions: (id, d) => request('PUT', `/api/books/${id}/decisions`, d),
  runLlm: (id, tasks) => request('POST', `/api/books/${id}/llm`, { tasks }),
  llmSettings: () => request('GET', '/api/settings/llm'),
  saveLlmSettings: (d) => request('PUT', '/api/settings/llm', d),
  testLlm: () => request('POST', '/api/settings/llm/test'),
  removeWaiver: (id, wid) => request('DELETE', `/api/books/${id}/waivers/${wid}`),
  downloadUrl: (id, which = 'fixed') => `/api/books/${id}/download?which=${which}`,
  // 独立阅读器：直接打开任意 EPUB 看，不建项目
  readerBooks: () => request('GET', '/api/reader'),
  readerOpen(file) {
    const fd = new FormData()
    fd.append('file', file)
    return request('POST', '/api/reader', fd)
  },
  readerRemove: (rid) => request('DELETE', `/api/reader/${rid}`),
  readerSpine: (rid) => request('GET', `/api/reader/${rid}/spine`),
}

export const STATUS = {
  queued: '排队中',
  converting: '转换中',
  auditing: '体检中',
  ready: '已体检',
  fixing: '修复中',
  thinking: '大模型分析中',
  fixed: '已修复',
  error: '出错',
}

export const BUSY = new Set(['queued', 'converting', 'auditing', 'fixing', 'thinking'])
// 能上传的格式：EPUB、TXT，以及 Kindle 的 MOBI / AZW / AZW3（后两类后台先转成 EPUB）
export const UPLOAD_EXTS = ['.epub', '.txt', '.mobi', '.azw', '.azw3']
