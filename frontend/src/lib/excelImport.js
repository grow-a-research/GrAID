// Converts an uploaded .xlsx file's first sheet into a CSV File client-side,
// so backend import endpoints only ever need to parse CSV. Mirrors the
// pattern already used for class-enrollment bulk import (see
// parseExcelStudentIds in ClassesPage.jsx), just producing a full CSV
// instead of extracting a single ID column.

export function isExcelFile(file) {
  return /\.(xlsx|xls)$/i.test(file.name)
}

export async function xlsxToCsvFile(file) {
  const XLSX = await import('xlsx')
  const buf = await file.arrayBuffer()
  const workbook = XLSX.read(buf, { type: 'array' })
  const sheet = workbook.Sheets[workbook.SheetNames[0]]
  const csv = XLSX.utils.sheet_to_csv(sheet)
  return new File([csv], file.name.replace(/\.(xlsx|xls)$/i, '.csv'), { type: 'text/csv' })
}

// Pass any CSV/XLSX file through this before uploading to a CSV-only endpoint.
export async function toCsvFile(file) {
  return isExcelFile(file) ? await xlsxToCsvFile(file) : file
}
