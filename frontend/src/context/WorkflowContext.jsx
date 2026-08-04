import { createContext, useContext, useState, useCallback } from 'react'

// Shares the "current exam / current submission" selection across the
// Exams → Submissions → Results tabs, so switching tabs doesn't force
// re-picking the same exam each time.
const WorkflowContext = createContext(null)

export function WorkflowProvider({ children }) {
  const [selectedExam, setSelectedExamState] = useState(null)
  const [selectedSubmission, setSelectedSubmissionState] = useState(null)

  // User explicitly picked a different exam — the old submission choice no longer applies.
  const selectExam = useCallback((exam) => {
    setSelectedExamState(exam)
    setSelectedSubmissionState(null)
  }, [])

  // Refresh the currently-selected exam's own data (e.g. after generating a template)
  // without disturbing whatever submission is selected.
  const updateSelectedExam = useCallback((examOrUpdater) => {
    setSelectedExamState(examOrUpdater)
  }, [])

  const selectSubmission = useCallback((sub) => {
    setSelectedSubmissionState(sub)
  }, [])

  // Refresh the currently-selected submission's own data (e.g. after upload/processing).
  const updateSelectedSubmission = useCallback((subOrUpdater) => {
    setSelectedSubmissionState(subOrUpdater)
  }, [])

  const clearWorkflow = useCallback(() => {
    setSelectedExamState(null)
    setSelectedSubmissionState(null)
  }, [])

  return (
    <WorkflowContext.Provider value={{
      selectedExam, selectExam, updateSelectedExam,
      selectedSubmission, selectSubmission, updateSelectedSubmission,
      clearWorkflow,
    }}>
      {children}
    </WorkflowContext.Provider>
  )
}

export function useWorkflow() {
  const ctx = useContext(WorkflowContext)
  if (!ctx) throw new Error('useWorkflow must be used within a WorkflowProvider')
  return ctx
}
