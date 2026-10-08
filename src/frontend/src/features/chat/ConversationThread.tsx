import { useEffect, useEffectEvent, useState } from 'react'
import type { ChatSummary, GenerationSettings, Paper } from '@/api/types'
import { useGenerationSettings } from '@/components/composer/generation-settings'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { Skeleton } from '@/components/ui/skeleton'
import { SummaryCard } from '@/features/summary'
import { peekQuestion, takeQuestion, type PendingQuestion } from '@/lib/pending-questions'
import { ConversationComposer } from './ConversationComposer'
import { AssistantMessage, PendingAnswer, UserMessage } from './Messages'
import { canAsk, questionGate } from './question-gate'
import { SuggestedQuestions } from './SuggestedQuestions'
import { ThreadLayout } from './ThreadLayout'
import { useChatStream } from './use-chat-stream'
import { useFollowBottom } from './use-follow-bottom'

const announcements = { completed: 'Response complete.', stopped: 'Generation stopped. The partial answer was kept.', failed: '' }

function HistorySkeleton() {
  return (
    <div role="status" aria-label="Loading conversation" className="grid gap-6">
      <Skeleton className="ml-auto h-10 w-2/5 rounded-2xl" />
      <div className="grid gap-2"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-11/12" /><Skeleton className="h-4 w-2/3" /></div>
    </div>
  )
}

/** One saved conversation: summary first, then the thread, with the composer docked below. */
export function ConversationThread({ paper, chat }: { paper: Paper; chat: ChatSummary }) {
  const generation = useGenerationSettings()
  const stream = useChatStream(chat)
  const [text, setText] = useState('')
  const gate = questionGate(paper, { usable: generation.usableFor('chat'), loading: generation.loading })
  const loaded = stream.history.isSuccess
  const ready = canAsk(gate) && loaded && !stream.busy

  const { saved, draft, pending } = stream
  const asked = saved.filter((message) => message.role === 'user').length
  // While streaming, the live draft stands in for its saved row; the optimistic question shows until saved.
  const rows = draft ? saved.map((message) => (message.id === draft.id ? draft : message)) : saved
  const question = pending && asked <= pending.baseline ? pending.text : null
  const unsavedDraft = draft && !saved.some((message) => message.id === draft.id) ? draft : null
  const empty = loaded && !rows.length && !question && !unsavedDraft && !stream.streaming
  const { scrollRef, onScroll, away, stick, toLatest } = useFollowBottom(`${rows.length}:${question ?? ''}:${draft?.id ?? ''}:${draft?.content.length ?? 0}:${draft?.state ?? ''}`)

  function ask(content: string, settings: GenerationSettings = generation.settings, requestId?: string) {
    stick()
    setText('')
    void stream.send(content, settings, requestId)
  }

  // A question queued by the home composer or the new-conversation start is sent once, with its own request_id.
  // Peek in the effect, send from a timer the cleanup clears: StrictMode's remount then sends exactly once.
  const sendQueued = useEffectEvent((queued: PendingQuestion) => {
    if (gate.locked || stream.busy) setText(queued.content)
    else ask(queued.content, queued.settings, queued.request_id)
  })
  useEffect(() => {
    if (!loaded || !peekQuestion(chat.id)) return
    const timer = window.setTimeout(() => {
      const queued = takeQuestion(chat.id)
      if (queued) sendQueued(queued)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [chat.id, loaded])

  const note = stream.processing && !stream.streaming
    ? 'An answer is still being written. It appears here when it finishes.'
    : chat.document_id !== paper.active_document_id ? 'This conversation uses an earlier PDF of this paper.' : null

  return (
    <ThreadLayout
      scrollRef={scrollRef}
      onScroll={onScroll}
      away={away}
      onLatest={toLatest}
      composer={
        <ConversationComposer
          value={text}
          onValueChange={setText}
          onSubmit={() => { if (ready) ask(text) }}
          gate={gate}
          sendable={loaded}
          busy={stream.busy}
          onStop={stream.streaming ? stream.stop : undefined}
          note={note}
        />
      }
    >
      <SummaryCard paper={paper} />
      {stream.history.isPending && <HistorySkeleton />}
      <ErrorNotice error={stream.history.error} retry={() => void stream.history.refetch()} />
      {empty && <SuggestedQuestions disabled={!ready} onSelect={(value) => { if (ready) ask(value) }} />}
      {rows.map((message) => message.role === 'user'
        ? <UserMessage key={message.id} content={message.content} />
        : <AssistantMessage key={message.id} message={message} documentId={chat.document_id} />)}
      {question && <UserMessage content={question} />}
      {unsavedDraft && <AssistantMessage message={unsavedDraft} documentId={chat.document_id} />}
      {stream.streaming && !draft && <PendingAnswer />}
      <ErrorNotice error={stream.error} />
      <p role="status" className="sr-only">{stream.streaming ? 'Assistant is responding.' : stream.outcome ? announcements[stream.outcome] : ''}</p>
    </ThreadLayout>
  )
}
