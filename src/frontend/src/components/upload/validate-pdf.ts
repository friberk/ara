export const MAX_PDF_BYTES = 25 * 1024 * 1024

/** Client-side checks mirror the server limits so a bad file is caught before uploading. */
export function validatePdf(file: File | null): string | null {
  if (!file) return null
  if (file.size > MAX_PDF_BYTES) return 'This PDF exceeds 25 MB. Choose a smaller file.'
  if (!(file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf'))) return 'Choose a PDF file.'
  return null
}
