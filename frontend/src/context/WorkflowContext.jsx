import { createContext, useContext, useState, useCallback } from 'react'

// Shares the "current class / current exam / current submission" selection
// across the Exams → Submissions → Results tabs, so switching tabs doesn't
// force re-picking the same class/exam each time.
const WorkflowContext = createContext(null)

export function WorkflowProvider({ children }) {
  const [selectedClass, setSelectedClassState] = useState(null)
  const [selectedExam, setSelectedExamState] = useState(null)
  const [selectedSubmission, setSelectedSubmissionState] = useState(null)

  // Picking a specific class that the current exam doesn't belong to drops the
  // exam/submission selection — otherwise the Submissions/Results panels would
  // keep showing data for an exam that the "browse by exam" list, scoped to the
  // new class, no longer even lists (confusing: filter says empty, data isn't).
  // Broadening back to "All classes" never invalidates anything, since every
  // exam is back in scope.
  const selectClass = useCallback((cls) => {
    setSelectedClassState(cls)
    if (!cls) return
    setSelectedExamState(prevExam => {
      if (!prevExam || prevExam.class_id === cls.id) return prevExam
      setSelectedSubmissionState(null)
      return null
    })
  }, [])

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
    setSelectedClassState(null)
    setSelectedExamState(null)
    setSelectedSubmissionState(null)
  }, [])

  return (
    <WorkflowContext.Provider value={{
      selectedClass, selectClass,
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
