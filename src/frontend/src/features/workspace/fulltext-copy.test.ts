import { retrievalProgress, sourceName, waitText } from './fulltext-copy'

test('Given a reported wait, Then short waits count seconds and long ones round up to minutes', () => {
  expect(waitText(1)).toBe('1 second')
  expect(waitText(45)).toBe('45 seconds')
  expect(waitText(89)).toBe('89 seconds')
  expect(waitText(238)).toBe('4 minutes')
})

test('Given a download host, Then progress names the source in plain words', () => {
  expect(sourceName('www.biorxiv.org')).toBe('biorxiv.org')
  expect(retrievalProgress({ state: 'processing', stage: 'fetching_pdf' }, 'pmc.ncbi.nlm.nih.gov')).toBe('Downloading the PDF from PubMed Central')
  expect(retrievalProgress({ state: 'processing', stage: 'fetching_pdf' }, null)).toBe('Downloading the PDF')
  expect(retrievalProgress({ state: 'queued', stage: 'queued' })).toBe('Looking for an open PDF')
})
