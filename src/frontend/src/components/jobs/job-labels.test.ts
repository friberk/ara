import { isActiveJob, jobKindLabel, jobStageLabel } from './job-labels'

test('Given job kinds and stages, Then readers see plain descriptions instead of internal names', () => {
  expect(jobKindLabel('ingest')).toBe('PDF processing')
  expect(jobKindLabel('summary')).toBe('Paper summary')
  expect(jobKindLabel('custom_kind')).toBe('custom kind')
  expect(jobStageLabel({ state: 'processing', stage: 'extracting_metadata' })).toBe('Extracting title, authors and abstract')
  expect(jobStageLabel({ state: 'processing', stage: 'summarizing' })).toBe('Summarizing sections')
  expect(jobStageLabel({ state: 'queued', stage: 'retry_wait' })).toBe('Waiting to retry')
  expect(jobStageLabel({ state: 'processing', stage: 'new_stage' })).toBe('new stage')
  expect(jobStageLabel({ state: 'completed', stage: 'anything' })).toBe('Completed')
  expect(jobStageLabel({ state: 'failed', stage: 'anything' })).toBe('Processing failed')
})

test('Given job states, Then only queued and processing jobs count as active', () => {
  expect(['queued', 'processing', 'completed', 'failed'].map((state) => isActiveJob({ state: state as 'queued' }))).toEqual([true, true, false, false])
})

test('Given full-text retrieval, Then its kind and stages describe PDF retrieval separately from model transfer', () => {
  expect(jobKindLabel('fulltext')).toBe('PDF retrieval')
  expect(jobStageLabel({ state: 'processing', stage: 'discovering_fulltext' })).toBe('Looking for a PDF')
  expect(jobStageLabel({ state: 'processing', stage: 'fetching_pdf' })).toBe('Downloading the PDF')
  expect(jobStageLabel({ state: 'processing', stage: 'storing_pdf' })).toBe('Saving the PDF')
})

test('Given model transfer stages, Then Activity uses readable labels and paused work stays unfinished', () => {
  expect(jobKindLabel('model_download')).toBe('Model download')
  expect(jobKindLabel('model_delete')).toBe('Model weights deletion')
  expect(jobStageLabel({ state: 'processing', stage: 'downloading' })).toBe('Downloading weights')
  expect(jobStageLabel({ state: 'processing', stage: 'pausing' })).toBe('Stopping the transfer')
  expect(jobStageLabel({ state: 'queued', stage: 'settling' })).toBe('Stopping download')
  expect(jobStageLabel({ state: 'paused', stage: 'paused' })).toBe('Paused')
  expect(isActiveJob({ state: 'paused' })).toBe(true)
})
