import { preparationSteps } from './preparation'

const job = (fields: object) => ({ state: 'processing', stage: 'processing', error: null, ...fields }) as Parameters<typeof preparationSteps>[0]['ingest']
const summary = (steps: ReturnType<typeof preparationSteps>) => steps.map((step) => `${step.label}:${step.state}${step.detail ? `:${step.detail}` : ''}`)

test('Given an upload in flight, Then Uploading is current with its percentage and the later steps wait', () => {
  expect(summary(preparationSteps({ upload: { progress: 0.42 }, documentStatus: 'metadata_only' }))).toEqual([
    'Uploading:active:42%', 'Reading pages:pending', 'Finding paper details:pending', 'Ready:pending',
  ])
})

test('Given a PDF that came from anywhere, When its pages are read, Then no upload step is claimed', () => {
  expect(summary(preparationSteps({ ingest: job({}), documentStatus: 'processing' }))).toEqual([
    'Reading pages:active', 'Finding paper details:pending', 'Ready:pending',
  ])
  expect(summary(preparationSteps({ uploaded: true, ingest: job({ state: 'queued', stage: 'queued' }), documentStatus: 'processing' }))[0]).toBe('Uploaded:done')
})

test('Given ingestion reading the title and authors, Then reading is done and paper details are current', () => {
  expect(summary(preparationSteps({ ingest: job({ stage: 'extracting_metadata' }), documentStatus: 'processing' }))).toEqual([
    'Reading pages:done', 'Finding paper details:active', 'Ready:pending',
  ])
})

test('Given a ready paper while its catalog lookup runs or waits, Then only the details step is unfinished', () => {
  expect(summary(preparationSteps({ lookup: job({}), documentStatus: 'ready' }))).toEqual([
    'Reading pages:done', 'Finding paper details:active', 'Ready:done',
  ])
  expect(summary(preparationSteps({ lookup: job({ state: 'queued', stage: 'retry_wait' }), documentStatus: 'ready' }))[1]).toBe('Finding paper details:active:Catalog busy, trying again shortly')
  expect(summary(preparationSteps({ lookup: job({ state: 'failed' }), documentStatus: 'ready' }))[1]).toBe('Finding paper details:done:Kept the details from the PDF')
})

test('Given ingestion failed, Then reading shows the failure and its reason', () => {
  const steps = preparationSteps({ ingest: job({ state: 'failed', error: { code: 'OCR_REQUIRED', message: 'No readable text found.' } }), documentStatus: 'failed' })
  expect(summary(steps)).toEqual(['Reading pages:failed:No readable text found.', 'Finding paper details:pending', 'Ready:pending'])
})
