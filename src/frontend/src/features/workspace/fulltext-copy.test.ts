import { retrievalProgress, waitText } from './fulltext-copy'

test('Given a reported wait, Then short waits count seconds, then minutes, then hours, rounding up', () => {
  expect(waitText(1)).toBe('1 second')
  expect(waitText(45)).toBe('45 seconds')
  expect(waitText(89)).toBe('89 seconds')
  expect(waitText(238)).toBe('4 minutes')
  expect(waitText(3600)).toBe('1 hour')
  // A countdown a few seconds into an hour-long wait still reads as one hour.
  expect(waitText(3598)).toBe('1 hour')
  expect(waitText(3500)).toBe('59 minutes')
  expect(waitText(5400)).toBe('2 hours')
})

test('Given each retrieval stage, Then progress names OpenAlex in plain words', () => {
  expect(retrievalProgress({ state: 'queued', stage: 'queued' })).toBe('Checking OpenAlex for a stored PDF')
  expect(retrievalProgress({ state: 'processing', stage: 'fetching_pdf' })).toBe('Downloading the PDF from OpenAlex')
  expect(retrievalProgress({ state: 'processing', stage: 'storing_pdf' })).toBe('Saving the PDF')
})
