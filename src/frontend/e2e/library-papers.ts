import { expect, type APIRequestContext } from '@playwright/test'
import { existsSync } from 'node:fs'
import { readFile } from 'node:fs/promises'

// Ready library papers for the fixture stack (compose.e2e.yaml), shared by the multi-paper and mention specs. The second
// paper is a separate synthetic PDF with its own embedded title, so its upload becomes its own library paper:
//   uv run --with pymupdf==1.26.7 python tests/fixtures/create_pdf.py --second /tmp/ara-fixtures/second.pdf
const pdfPath = process.env.E2E_PDF_PATH ?? '/tmp/ara-fixtures/research.pdf'
const secondPath = process.env.E2E_SECOND_PDF_PATH ?? '/tmp/ara-fixtures/second.pdf'
export const firstTitle = 'Traceable Research Systems'
export const secondTitle = 'Sparse Indexes for Lab Notebooks'
export type Paper = { id: string; document_status: string }

export async function ready(request: APIRequestContext, paperId: string) {
  await expect.poll(async () => (await (await request.get(`/api/v1/papers/${paperId}`)).json()).document_status, { timeout: 45_000 }).toBe('ready')
}

export async function fixturePaper(request: APIRequestContext): Promise<Paper> {
  const response = await request.post('/api/v1/papers', { data: { provider: 'openalex', external_id: 'W123456789' } })
  expect(response.ok()).toBeTruthy()
  const paper = await response.json() as Paper
  if (paper.document_status !== 'ready') {
    expect(existsSync(pdfPath), 'Generate the synthetic research.pdf before browser checks').toBeTruthy()
    const upload = await request.post('/api/v1/documents', { multipart: { file: { name: 'research.pdf', mimeType: 'application/pdf', buffer: await readFile(pdfPath) }, paper_id: paper.id, request_id: crypto.randomUUID() } })
    expect(upload.ok()).toBeTruthy()
    await ready(request, paper.id)
  }
  return paper
}

/** The second paper, uploaded once; a repeat upload answers with the same paper. */
export async function secondPaper(request: APIRequestContext): Promise<Paper> {
  expect(existsSync(secondPath), 'Generate the second synthetic PDF (create_pdf.py --second) before browser checks').toBeTruthy()
  const upload = await request.post('/api/v1/documents', { multipart: { file: { name: 'second.pdf', mimeType: 'application/pdf', buffer: await readFile(secondPath) }, request_id: crypto.randomUUID() } })
  expect(upload.ok()).toBeTruthy()
  const { paper_id: paperId } = await upload.json() as { paper_id: string }
  await ready(request, paperId)
  return { id: paperId, document_status: 'ready' }
}
