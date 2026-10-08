import { peekQuestion, queueQuestion, takeQuestion } from './pending-questions'

test('Given a queued question, Then it can be peeked repeatedly but taken exactly once with a fixed request id', () => {
  queueQuestion('c1', { content: 'What datasets are used?', settings: { model: 'gpt-5.6-luna', reasoning_effort: 'low' } })
  const first = peekQuestion('c1')
  expect(first).toMatchObject({ content: 'What datasets are used?', settings: { model: 'gpt-5.6-luna', reasoning_effort: 'low' } })
  expect(first?.request_id).toMatch(/^[0-9a-f-]{36}$/)
  expect(peekQuestion('c1')?.request_id).toBe(first?.request_id)
  expect(takeQuestion('c1')).toEqual(first)
  expect(takeQuestion('c1')).toBeUndefined()
  expect(peekQuestion('c1')).toBeUndefined()
})

test('Given questions for two chats, Then each chat only receives its own', () => {
  queueQuestion('a', { content: 'first', settings: { model: 'm', reasoning_effort: 'low' } })
  queueQuestion('b', { content: 'second', settings: { model: 'm', reasoning_effort: 'low' } })
  expect(takeQuestion('b')?.content).toBe('second')
  expect(takeQuestion('a')?.content).toBe('first')
})
