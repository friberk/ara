import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { checkedResponse, json } from '@/api/client'
import { readEvents } from '@/api/sse'
import type { Chat, ChatInput, GenerationSettings, Message, RetrievalStage } from '@/api/types'
import { useMessages } from '@/hooks/queries/chats'
import { trimDraft, type Draft, type DraftMention } from '@/lib/mentions'
import { queryKeys } from '@/lib/query-keys'

export type StreamOutcome = 'completed' | 'stopped' | 'failed'
/** The question shown before the server saves it; baseline is how many questions were saved when it was sent. */
type PendingQuestion = { text: string; mentions: DraftMention[]; baseline: number }

const isAbort = (error: unknown) => error instanceof DOMException && error.name === 'AbortError'
const stages: ReadonlySet<string> = new Set<RetrievalStage>(['waiting', 'planning', 'retrieving', 'reranking', 'generating', 'widening', 'mapping'])

/**
 * One chat's saved history plus the answer being streamed into it (ported from the legacy ChatPanel send()).
 *
 * Nothing here resends a question: a stream that ends early says so and leaves the saved state to the server.
 * Stop keeps the partial answer, unmounting aborts, and the saved history replaces local drafts once persisted.
 * A supplied request_id (a queued question) replays the stored answer if the same question is ever sent twice.
 */
export function useChatStream(chat: Pick<Chat, 'id' | 'papers'>) {
  const client = useQueryClient()
  const [streaming, setStreaming] = useState(false)
  const [draft, setDraft] = useState<Message | null>(null)
  const [pending, setPending] = useState<PendingQuestion | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [outcome, setOutcome] = useState<StreamOutcome | null>(null)
  // The step the server reports while the answer is prepared; unknown stages keep the last known one.
  const [stage, setStage] = useState<RetrievalStage | null>(null)
  const controller = useRef<AbortController | null>(null)
  const inFlight = useRef(false)
  const mounted = useRef(true)
  const history = useMessages(chat.id, { streaming })
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; controller.current?.abort() } }, [])

  const saved = history.data?.items ?? []
  const processing = saved.some((message) => message.state === 'processing')
  const busy = streaming || processing
  // Context used and cost change with every answer, finished or not: planning and search are billed first.
  const refreshUsage = () => void client.invalidateQueries({ queryKey: queryKeys.usage.chat(chat.id) })
  const refreshChats = () => void client.invalidateQueries({ queryKey: queryKeys.chats.all })
  // A completed answer may have moved earlier messages into the chat's summary.
  const refreshMemory = () => void client.invalidateQueries({ queryKey: queryKeys.retrieval.memory(chat.id) })

  async function send(question: Draft, settings: GenerationSettings, requestId: string = crypto.randomUUID()) {
    const { text, mentions } = trimDraft(question)
    if (!text || busy || inFlight.current) return
    inFlight.current = true
    const abort = new AbortController()
    controller.current = abort
    const baseline = saved.filter((message) => message.role === 'user').length
    setStreaming(true); setError(null); setDraft(null); setOutcome(null); setStage(null); setPending({ text, mentions, baseline })
    // Papers the question mentions join the chat with it (ARA-096), so its answer may cite them.
    const joining = new Set(mentions.map((mention) => mention.paper_id).filter((id) => !chat.papers.some((paper) => paper.paper_id === id)))
    const answer = (id: string, partial = ''): Message => ({ id, role: 'assistant', content: partial, state: 'processing', model: settings.model, reasoning_effort: settings.reasoning_effort, citations: [], created_at: new Date().toISOString() })
    let terminal = false
    let completed = false
    try {
      const sent = mentions.map(({ paper_id, label, start, end }) => ({ paper_id, label, start, end }))
      const response = await checkedResponse(`/chats/${chat.id}/messages/stream`, { ...json('POST', { content: text, mentions: sent, ...settings, request_id: requestId } satisfies ChatInput), signal: abort.signal })
      await readEvents(response, (event) => {
        if (!mounted.current) return
        if (terminal) throw new Error('The server sent events after the response completed. Reload the conversation.')
        if (event.event === 'message.started') {
          setDraft(answer(event.data.message_id))
          // The question is saved, and may have titled the chat, before the answer starts.
          refreshChats()
        }
        if (event.event === 'message.status' && stages.has(event.data.stage)) setStage(event.data.stage as RetrievalStage)
        // The first answer found too little: the wider retry replaces it, so its text goes (ARA-094).
        if (event.event === 'message.status' && event.data.stage === 'widening') setDraft((previous) => previous ? { ...previous, content: '' } : previous)
        if (event.event === 'message.delta') setDraft((previous) => previous ? { ...previous, content: previous.content + event.data.text } : answer('stream', event.data.text))
        if (event.event === 'message.completed') {
          const documents = new Set(chat.papers.map((paper) => paper.document_id))
          if (event.data.citations.some((citation) => !documents.has(citation.document_id) && !(citation.paper_id && joining.has(citation.paper_id)))) throw new Error(`The response included a source outside ${chat.papers.length > 1 ? 'these papers' : 'this document'}.`)
          terminal = true
          completed = true
          setDraft(event.data)
          setOutcome('completed')
        }
        if (event.event === 'message.failed') {
          terminal = true
          setError(new Error(event.data.message))
          setOutcome('failed')
          setDraft((previous) => previous ? { ...previous, state: 'failed' } : null)
        }
      })
      if (!terminal) throw new Error('The response ended early. Your question was not automatically sent again. Reload the conversation to check its saved state.')
    } catch (caught) {
      if (mounted.current) {
        // Stop is the reader's choice, not an error: the partial answer stays and is marked interrupted.
        if (!isAbort(caught)) setError(caught instanceof Error ? caught : new Error('The response failed. Reload the conversation.'))
        setOutcome(isAbort(caught) ? 'stopped' : 'failed')
        setDraft((previous) => previous ? { ...previous, state: 'interrupted' } : null)
      }
    } finally {
      controller.current = null
      inFlight.current = false
      if (mounted.current) {
        setStreaming(false)
        setStage(null)
        const refreshed = await history.refetch()
        if (refreshed.data && mounted.current) {
          const items = refreshed.data.items
          if (items.filter((message) => message.role === 'user').length > baseline) setPending(null)
          setDraft((previous) => previous && items.some((message) => message.id === previous.id) ? null : previous)
        }
        refreshChats()
        refreshUsage()
        if (completed) refreshMemory()
      }
    }
  }

  return { history, saved, draft, pending, streaming, processing, busy, error, outcome, stage, send, stop: () => controller.current?.abort() }
}
