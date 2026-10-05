// Shared display labels for FlagLog.flag_reason / review_decision.
// Used by the per-answer flag badge (ResultsPage) and the exam-wide
// Flagged Answers page — kept in one place so they can't drift apart.

export const REASON_LABELS = {
  essay_score_zero:       'Zero score',
  // Kept for answers flagged before the combined-confidence rule replaced it.
  essay_low_confidence:   'Low AI confidence',
  essay_low_transcription_confidence: 'Low transcription confidence',
  essay_low_grading_confidence:       'Low grading confidence',
  omr_low_confidence:     'Low OMR confidence',
  omr_no_detection:       'No bubble detected',
  identification_no_match:'No match',
  identification_ocr_unreadable:'Unreadable OCR',
  manual:                 'Manual flag',
  verified:               'Verified',
}

export const DECISION_COLOR = {
  confirmed_error: 'border-red-700 bg-red-950/40 text-red-300',
  false_positive:  'border-zinc-700 bg-zinc-800/40 text-zinc-400',
  verified:        'border-emerald-800 bg-emerald-950/30 text-emerald-400',
}
