const BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'
const V1 = `${BASE}/api/v1`

// ── Session (one signed-in role per browser tab-set) ─────────────────────────
const SESSION_KEY = 'graid_session'

export function getSession() {
  try {
    const s = JSON.parse(localStorage.getItem(SESSION_KEY))
    // Ignore a corrupted/partial session instead of crashing the app on it.
    return s && s.token && s.role && s.user ? s : null
  } catch { return null }
}
function setSession(s) {
  try { localStorage.setItem(SESSION_KEY, JSON.stringify(s)) } catch {}
}
function clearSession() {
  try { localStorage.removeItem(SESSION_KEY) } catch {}
}

function authHeaders(extra = {}) {
  const t = getSession()?.token
  return t ? { ...extra, Authorization: `Bearer ${t}` } : extra
}

// <img src>, <a href> and window.open cannot send headers, so links to
// protected files carry the token in the query string.
function withToken(url) {
  const t = getSession()?.token
  if (!t) return url
  return `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(t)}`
}

async function fail(r) {
  // An expired/invalid token on a protected call → drop the session and show login.
  if (r.status === 401 && getSession()) {
    clearSession()
    window.dispatchEvent(new Event('graid-auth-changed'))
  }
  const text = await r.text()
  let detail = text
  try {
    const d = JSON.parse(text)?.detail
    detail = typeof d === 'string' ? d : (d ? JSON.stringify(d) : text)
  } catch {}
  throw new Error(detail)
}

async function req(method, url, body) {
  const init = { method, headers: authHeaders() }
  if (body !== undefined) {
    init.headers = authHeaders({ 'Content-Type': 'application/json' })
    init.body = JSON.stringify(body)
  }
  const r = await fetch(url, init)
  if (!r.ok) await fail(r)
  if (r.status === 204) return null
  return r.json()
}

async function upload(url, file, extraQuery = '') {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`${url}${extraQuery}`, { method: 'POST', headers: authHeaders(), body: fd })
  if (!r.ok) await fail(r)
  return r.json()
}

// Fetches a protected file and saves it straight to disk. A plain link would let
// the browser open PDFs in a preview tab (and cross-origin links ignore the
// `download` attribute), so this fetches the bytes and saves them itself.
export async function downloadFile(url, filename) {
  const r = await fetch(url, { headers: authHeaders() })
  if (!r.ok) await fail(r)
  const blob = await r.blob()
  const a = document.createElement('a')
  const href = URL.createObjectURL(blob)
  a.href = href
  a.download = (filename || 'download').replace(/[\\/:*?"<>|]+/g, '_')
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}

export const api = {
  download: downloadFile,

  // ── Auth (separate flows per role) ─────────────────────────────────────────
  auth: {
    async login(role, email, password) {
      const res = await req('POST', `${V1}/auth/${role}/login`, { email, password })
      setSession({ token: res.token, role: res.role, user: res.user })
      return res
    },
    async register(role, body) {
      const res = await req('POST', `${V1}/auth/${role}/register`, body)
      setSession({ token: res.token, role: res.role, user: res.user })
      return res
    },
    async logout() {
      const sess = getSession()
      try { if (sess) await req('POST', `${V1}/auth/${sess.role}/logout`) } catch {}
      clearSession()
    },
  },

  // ── Student portal ─────────────────────────────────────────────────────────
  student: {
    profile: () => req('GET', `${V1}/student/profile`),
    enroll: (code) => req('POST', `${V1}/student/enroll`, { code }),
    classes: () => req('GET', `${V1}/student/classes`),
    exams: () => req('GET', `${V1}/student/exams`),
    questions: (examId) => req('GET', `${V1}/student/exams/${examId}/questions`),
    results: (examId) => req('GET', `${V1}/student/exams/${examId}/results`),
    templateUrl: (examId) => withToken(`${V1}/student/exams/${examId}/template`),
    submission: (examId) => req('GET', `${V1}/student/exams/${examId}/submission`),
    uploadFile: async (examId, file, page = 1) => {
      const fd = new FormData()
      fd.append('file', file)
      const r = await fetch(`${V1}/student/exams/${examId}/submission/files?page_number=${page}`,
        { method: 'POST', headers: authHeaders(), body: fd })
      if (!r.ok) await fail(r)
      return r.json()
    },
    deleteFile: (examId, fileId) =>
      req('DELETE', `${V1}/student/exams/${examId}/submission/files/${fileId}`),
    submit: (examId) => req('POST', `${V1}/student/exams/${examId}/submission/submit`),
    unsubmit: (examId) => req('POST', `${V1}/student/exams/${examId}/submission/unsubmit`),
  },

  // ── Classes ────────────────────────────────────────────────────────────────
  classes: {
    list: () => req('GET', `${V1}/classes`),
    create: (body) => req('POST', `${V1}/classes`, body),
    delete: (id) => req('DELETE', `${V1}/classes/${id}`),
    // Roster carries each student's access code; `id` keeps list keys stable.
    enrolled: async (classId) =>
      (await req('GET', `${V1}/classes/${classId}/roster`)).map(r => ({ ...r, id: r.student_id })),
    regenerateCode: (classId, studentId) =>
      req('POST', `${V1}/classes/${classId}/enrollments/${studentId}/regenerate-code`),
    enroll: (classId, studentId) =>
      req('POST', `${V1}/classes/${classId}/enrollments`, { student_id: studentId }),
    enrollBulk: (classId, studentIds) =>
      req('POST', `${V1}/classes/${classId}/enrollments/bulk`, { student_ids: studentIds }),
    unenroll: (classId, studentId) =>
      req('DELETE', `${V1}/classes/${classId}/enrollments/${studentId}`),
    analytics: (classId) => req('GET', `${V1}/classes/${classId}/analytics`),
  },

  // ── Students ───────────────────────────────────────────────────────────────
  students: {
    list: () => req('GET', `${V1}/students`),
    create: (body) => req('POST', `${V1}/students`, body),
    update: (studentId, body) => req('PATCH', `${V1}/students/${studentId}`, body),
    delete: (studentId) => req('DELETE', `${V1}/students/${studentId}`),
    bulkDelete: (studentIds) => req('POST', `${V1}/students/bulk-delete`, { student_ids: studentIds }),
    import: (file) => upload(`${V1}/students/import`, file),
    analytics: (studentId) => req('GET', `${V1}/students/${studentId}/analytics`),
    analyze: (studentId) => req('POST', `${V1}/students/${studentId}/analyze`),
  },

  // ── Exams ──────────────────────────────────────────────────────────────────
  exams: {
    list: (classId) =>
      req('GET', `${V1}/exams${classId ? `?class_id=${classId}` : ''}`),
    create: (body) => req('POST', `${V1}/exams`, body),
    // due_at: ISO instant, or null to remove the deadline.
    get: (examId) => req('GET', `${V1}/exams/${examId}`),
    setAutoGrade: (examId, enabled) =>
      req('PATCH', `${V1}/exams/${examId}/auto-grade`, { enabled }),
    setResultsRelease: (examId, released) =>
      req('PATCH', `${V1}/exams/${examId}/results-release`, { released }),
    setDeadline: (examId, dueAt) => req('PATCH', `${V1}/exams/${examId}/deadline`, { due_at: dueAt }),
    delete: (id) => req('DELETE', `${V1}/exams/${id}`),
    questions: {
      list: (examId) => req('GET', `${V1}/exams/${examId}/questions`),
      add: (examId, body) => req('POST', `${V1}/exams/${examId}/questions`, body),
      update: (examId, qId, body) => req('PATCH', `${V1}/exams/${examId}/questions/${qId}`, body),
      delete: (examId, qId) => req('DELETE', `${V1}/exams/${examId}/questions/${qId}`),
      import: (examId, file) => upload(`${V1}/exams/${examId}/questions/import`, file),
      rubricCriteria: {
        parse: (examId, file) => upload(`${V1}/exams/${examId}/rubric-criteria/parse`, file),
      },
    },
    batchUpload: (examId, files) => {
      const fd = new FormData()
      files.forEach(f => fd.append('files', f))
      return fetch(`${V1}/exams/${examId}/submissions/batch`, { method: 'POST', headers: authHeaders(), body: fd })
        .then(async r => {
          if (!r.ok) await fail(r)
          return r.json()
        })
    },
    generateTemplate: (examId) => req('POST', `${V1}/exams/${examId}/template`),
    templatePdfUrl: (examId) => withToken(`${V1}/exams/${examId}/template/pdf`),
    questionnairePdfUrl: (examId) => withToken(`${V1}/exams/${examId}/questionnaire/pdf`),
    rubricPdfUrl: (examId) => withToken(`${V1}/exams/${examId}/rubric/pdf`),
    allPapersZipUrl: (examId) => withToken(`${V1}/exams/${examId}/papers/zip`),
    submissions: (examId) => req('GET', `${V1}/exams/${examId}/submissions`),
    // Creates one draft submission per enrolled student; skips students that
    // already have one, so it is safe to click more than once.
    bulkCreateSubmissions: (examId) =>
      req('POST', `${V1}/exams/${examId}/submissions/bulk`),
    analytics: (examId) => req('GET', `${V1}/exams/${examId}/analytics`),
    itemResponses: (examId, questionId) =>
      req('GET', `${V1}/exams/${examId}/questions/${questionId}/responses`),
    analyze: (examId) => req('POST', `${V1}/exams/${examId}/analyze`),
    duplicate: (examId) => req('POST', `${V1}/exams/${examId}/duplicate`),
    gradesCsvUrl: (examId) => withToken(`${V1}/exams/${examId}/grades/csv`),
    flagStats: (examId) => req('GET', `${V1}/exams/${examId}/flagstats`),
    reviewQueue: (examId) => req('GET', `${V1}/exams/${examId}/review-queue`),
    flags: (examId) => req('GET', `${V1}/exams/${examId}/flags`),
    rubrics: {
      import: (examId, file) => upload(`${V1}/exams/${examId}/rubrics/import`, file),
      clear: (examId) => req('DELETE', `${V1}/exams/${examId}/rubrics`),
    },
    processAll: (examId) => req('POST', `${V1}/exams/${examId}/submissions/process-all`),
    processAllStatus: (examId) => req('GET', `${V1}/exams/${examId}/submissions/process-all/status`),
  },

  // ── Submissions ────────────────────────────────────────────────────────────
  submissions: {
    create: (body) => req('POST', `${V1}/submissions`, body),
    get: (id) => req('GET', `${V1}/submissions/${id}`),
    delete: (id) => req('DELETE', `${V1}/submissions/${id}`),
    uploadFile: (id, file, page = 1) =>
      upload(`${V1}/submissions/${id}/files`, file, `?page_number=${page}`),
    deleteFile: (id, fileId) => req('DELETE', `${V1}/submissions/${id}/files/${fileId}`),
    runOcr: (id) => req('POST', `${V1}/submissions/${id}/ocr`),
    grade: (id, params = {}) => {
      const qs = new URLSearchParams(params).toString()
      return req('POST', `${V1}/submissions/${id}/grade${qs ? '?' + qs : ''}`)
    },
    answers: (id) => req('GET', `${V1}/submissions/${id}/answers`),
    override: (subId, answerId, body) =>
      req('PATCH', `${V1}/submissions/${subId}/answers/${answerId}`, body),
    flags: (subId) => req('GET', `${V1}/submissions/${subId}/flags`),
    markReviewed: (subId, answerId) =>
      req('POST', `${V1}/submissions/${subId}/answers/${answerId}/reviewed`),
    unmarkReviewed: (subId, answerId) =>
      req('DELETE', `${V1}/submissions/${subId}/answers/${answerId}/reviewed`),
    createFlag: (subId, answerId, body) =>
      req('POST', `${V1}/submissions/${subId}/answers/${answerId}/flag`, body),
    reviewFlag: (subId, answerId, body) =>
      req('PATCH', `${V1}/submissions/${subId}/answers/${answerId}/flag`, body),
    deleteFlag: (subId, answerId) =>
      req('DELETE', `${V1}/submissions/${subId}/answers/${answerId}/flag`),
    paperUrl: (id) => withToken(`${V1}/submissions/${id}/paper`),
    alignedImageUrl: (id, page = 1) => withToken(`${V1}/submissions/${id}/aligned-image/${page}`),
    originalImageUrl: (id, page = 1) => withToken(`${V1}/submissions/${id}/original-image/${page}`),
  },

  // ── Notifications (teacher) ────────────────────────────────────────────────
  notifications: {
    list: () => req('GET', `${V1}/notifications`),
    read: (id) => req('POST', `${V1}/notifications/${id}/read`),
    readAll: () => req('POST', `${V1}/notifications/read-all`),
  },

  // ── Queue (Phase 21) ──────────────────────────────────────────────────────
  queue: {
    enqueue: (examId) => req('POST', `${V1}/queue/enqueue/${examId}`),
    status:  ()       => req('GET',  `${V1}/queue/status`),
    // Re-run OCR + grading for chosen submissions, including already-graded
    // ones; returns immediately and the work happens in the background queue.
    reprocess: (ids)  => req('POST', `${V1}/queue/reprocess`, { submission_ids: ids }),
  },

  // ── Legacy OCR (Phase 2) ───────────────────────────────────────────────────
  extract: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return fetch(`${BASE}/extract`, { method: 'POST', headers: authHeaders(), body: fd }).then(async r => {
      if (!r.ok) await fail(r)
      return r.json()
    })
  },
}
