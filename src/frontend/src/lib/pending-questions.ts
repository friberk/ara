import type { GenerationSettings } from '@/api/types'

/**
 * Hand-off for "ask a library paper" from the home composer (ARA-038) to the conversation (ARA-036).
 *
 * The home page creates the chat, queues the question here and navigates. The conversation consumes it
 * exactly once. The request_id is fixed at queue time, so even an accidental second send replays the stored
 * answer instead of paying for a new generation.
 *
 * Consume it StrictMode-safely: peek in an effect, send from a zero-delay timer, clear the timer in cleanup,
 * and call takeQuestion inside the timer. StrictMode's mount, unmount, mount cycle then sends once.
 */
export type PendingQuestion = { content: string; settings: GenerationSettings; request_id: string }

const pending = new Map<string, PendingQuestion>()

export function queueQuestion(chatId: string, question: Omit<PendingQuestion, 'request_id'>) {
  pending.set(chatId, { ...question, request_id: crypto.randomUUID() })
}
export function peekQuestion(chatId: string) { return pending.get(chatId) }
export function takeQuestion(chatId: string) {
  const question = pending.get(chatId)
  pending.delete(chatId)
  return question
}
