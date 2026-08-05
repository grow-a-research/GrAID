const BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000'
const V1 = `${BASE}/api/v1`

async function req(method, url, body) {
  const init = { method }
  if (body !== undefined) {
    init.headers = { 'Content-Type': 'application/json' }
    init.body = JSON.stringify(body)
  }
  const r = await fetch(url, init)
  if (!r.ok) {
    const text = await r.text()
    let detail = text
    try { detail = JSON.parse(text)?.detail ?? text } catch {}
    throw new Error(detail)
  }
  if (r.status === 204) return null
  return r.json()
}

async function upload(url, file, extraQuery = '') {
  const fd = new FormData()
  fd.append('file', file)
  const r = await fetch(`${url}${extraQuery}`, { method: 'POST', body: fd })
  if (!r.ok) {
    const text = await r.text()
    let detail = text
    try { detail = JSON.parse(text)?.detail ?? text } catch {}
    throw new Error(detail)
  }
  return r.json()
}

export const api = {
  // ── Classes ────────────────────────────────────────────────────────────────
  classes: {
    list: () => req('GET', `${V1}/classes`),
    create: (body) => req('POST', `${V1}/classes`, body),
    delete: (id) => req('DELETE', `${V1}/classes/${id}`),
    enrolled: (classId) => req('GET', `${V1}/classes/${classId}/enrollments`),
    enroll: (classId, studentId) =>
      req('POST', `${V1}/classes/${classId}/enrollments`, { student_id: studentId }),
    enrollBulk: (classId, studentIds) =>
      req('POST', `${V1}/classes/${classId}/enrollments/bulk`, { student_ids: studentIds }),
    analytics: (classId) => req('GET', `${V1}/classes/${classId}/analytics`),
  },

  // ── Students ───────────────────────────────────────────────────────────────
  students: {
    list: () => req('GET', `${V1}/students`),
    create: (body) => req('POST', `${V1}/students`, body),
    update: (studentId, body) => req('PATCH', `${V1}/students/${studentId}`, body),
    delete: (studentId) => req('DELETE', `${V1}/students/${studentId}`),
    import: (file) => upload(`${V1}/students/import`, file),
    analytics: (studentId) => req('GET', `${V1}/students/${studentId}/analytics`),
    analyze: (studentId) => req('POST', `${V1}/students/${studentId}/analyze`),
  },

  // ── Exams ──────────────────────────────────────────────────────────────────
  exams: {
    list: (classId) =>
      req('GET', `${V1}/exams${classId ? `?class_id=${classId}` : ''}`),
    create: (body) => req('POST', `${V1}/exams`, body),
    delete: (id) => req('DELETE', `${V1}/exams/${id}`),
    questions: {
      list: (examId) => req('GET', `${V1}/exams/${examId}/questions`),
      add: (examId, body) => req('POST', `${V1}/exams/${examId}/questions`, body),
      update: (examId, qId, body) => req('PATCH', `${V1}/exams/${examId}/questions/${qId}`, body),
      delete: (examId, qId) => req('DELETE', `${V1}/exams/${examId}/questions/${qId}`),
      import: (examId, file) => upload(`${V1}/exams/${examId}/questions/import`, file),
    },
    batchUpload: (examId, files) => {
      const fd = new FormData()
      files.forEach(f => fd.append('files', f))
      return fetch(`${V1}/exams/${examId}/submissions/batch`, { method: 'POST', body: fd })
        .then(async r => {
          if (!r.ok) { const t = await r.text(); throw new Error(JSON.parse(t)?.detail ?? t) }
          return r.json()
        })
    },
    generateTemplate: (examId) => req('POST', `${V1}/exams/${examId}/template`),
    templatePdfUrl: (examId) => `${V1}/exams/${examId}/template/pdf`,
    questionnairePdfUrl: (examId) => `${V1}/exams/${examId}/questionnaire/pdf`,
    allPapersZipUrl: (examId) => `${V1}/exams/${examId}/papers/zip`,
    submissions: (examId) => req('GET', `${V1}/exams/${examId}/submissions`),
    analytics: (examId) => req('GET', `${V1}/exams/${examId}/analytics`),
    analyze: (examId) => req('POST', `${V1}/exams/${examId}/analyze`),
    duplicate: (examId) => req('POST', `${V1}/exams/${examId}/duplicate`),
    gradesCsvUrl: (examId) => `${V1}/exams/${examId}/grades/csv`,
    flagStats: (examId) => req('GET', `${V1}/exams/${examId}/flagstats`),
    rubrics: {
      import: (examId, file) => upload(`${V1}/exams/${examId}/rubrics/import`, file),
      clear: (examId) => req('DELETE', `${V1}/exams/${examId}/rubrics`),
    },
    processAll: (examId) => req('POST', `${V1}/exams/${examId}/submissions/process-all`),
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
    createFlag: (subId, answerId, body) =>
      req('POST', `${V1}/submissions/${subId}/answers/${answerId}/flag`, body),
    reviewFlag: (subId, answerId, body) =>
      req('PATCH', `${V1}/submissions/${subId}/answers/${answerId}/flag`, body),
    deleteFlag: (subId, answerId) =>
      req('DELETE', `${V1}/submissions/${subId}/answers/${answerId}/flag`),
    paperUrl: (id) => `${V1}/submissions/${id}/paper`,
    alignedImageUrl: (id, page = 1) => `${V1}/submissions/${id}/aligned-image/${page}`,
    originalImageUrl: (id, page = 1) => `${V1}/submissions/${id}/original-image/${page}`,
  },

  // ── Queue (Phase 21) ──────────────────────────────────────────────────────
  queue: {
    enqueue: (examId) => req('POST', `${V1}/queue/enqueue/${examId}`),
    status:  ()       => req('GET',  `${V1}/queue/status`),
  },

  // ── Legacy OCR (Phase 2) ───────────────────────────────────────────────────
  extract: (file) => {
    const fd = new FormData()
    fd.append('file', file)
    return fetch(`${BASE}/extract`, { method: 'POST', body: fd }).then(async r => {
      if (!r.ok) throw new Error(await r.text())
      return r.json()
    })
  },
}
