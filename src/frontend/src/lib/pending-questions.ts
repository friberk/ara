import type { GenerationSettings } from '@/api/types'
import type { DraftMention } from '@/lib/mentions'

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
export type PendingQuestion = { content: string; mentions: DraftMention[]; settings: GenerationSettings; request_id: string }

const pending = new Map<string, PendingQuestion>()

/** `mentions` are the question's pills (ARA-096), sent with it so their papers join the chat. */
export function queueQuestion(chatId: string, { mentions = [], ...question }: Omit<PendingQuestion, 'request_id' | 'mentions'> & { mentions?: DraftMention[] }) {
  pending.set(chatId, { ...question, mentions, request_id: crypto.randomUUID() })
}
export function peekQuestion(chatId: string) { return pending.get(chatId) }
export function takeQuestion(chatId: string) {
  const question = pending.get(chatId)
  pending.delete(chatId)
  return question
}
