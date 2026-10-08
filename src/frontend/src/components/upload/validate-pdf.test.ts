import { MAX_PDF_BYTES, validatePdf } from './validate-pdf'

function file(name: string, type: string, size = 1024) { const value = new File(['%PDF'], name, { type }); Object.defineProperty(value, 'size', { value: size }); return value }

test('Given PDFs by type or extension within 25 MB, Then they are accepted', () => {
  expect(validatePdf(file('paper.pdf', 'application/pdf'))).toBeNull()
  expect(validatePdf(file('PAPER.PDF', ''))).toBeNull()
  expect(validatePdf(file('edge.pdf', 'application/pdf', MAX_PDF_BYTES))).toBeNull()
  expect(validatePdf(null)).toBeNull()
})

test('Given an oversized file or a non-PDF, Then the reason and recovery are explained', () => {
  expect(validatePdf(file('large.pdf', 'application/pdf', MAX_PDF_BYTES + 1))).toBe('This PDF exceeds 25 MB. Choose a smaller file.')
  expect(validatePdf(file('notes.docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'))).toBe('Choose a PDF file.')
})
