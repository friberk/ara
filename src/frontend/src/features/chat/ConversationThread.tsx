import { useEffect, useEffectEvent, useMemo, useRef, useState } from 'react'
import type { ChatSummary, GenerationSettings, Paper, RetrievalStage } from '@/api/types'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { restoreChatSettings } from '@/components/composer/reasoning'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { Skeleton } from '@/components/ui/skeleton'
import { SummaryCard } from '@/features/summary'
import { useChatMemory } from '@/hooks/queries/retrieval'
import { peekQuestion, takeQuestion, type PendingQuestion } from '@/lib/pending-questions'
import { usePdfComing } from '@/hooks/queries/uploads'
import { ConversationComposer } from './ConversationComposer'
import { MemoryNote } from './MemoryNote'
import { AssistantMessage, PendingAnswer, UserMessage } from './Messages'
import { canAsk, questionGate } from './question-gate'
import { SuggestedQuestions } from './SuggestedQuestions'
import { ThreadLayout } from './ThreadLayout'
import { useChatSources } from './chat-sources'
import type { PaperSelection } from './ConversationComposer'
import { useChatStream } from './use-chat-stream'
import { useFollowBottom } from './use-follow-bottom'

const announcements = { completed: 'Response complete.', stopped: 'Generation stopped. The partial answer was kept.', failed: '' }
const stageLabels: Record<RetrievalStage, string> = { waiting: 'Waiting for the local model…', planning: 'Searching the paper…', retrieving: 'Searching the paper…', reranking: 'Searching the paper…', generating: 'Writing the answer…' }

function HistorySkeleton() {
  return (
    <div role="status" aria-label="Loading conversation" className="grid gap-6">
      <Skeleton className="ml-auto h-10 w-2/5 rounded-2xl" />
      <div className="grid gap-2"><Skeleton className="h-4 w-full" /><Skeleton className="h-4 w-11/12" /><Skeleton className="h-4 w-2/3" /></div>
    </div>
  )
}

/**
 * One saved conversation: summary first, then the thread, with the composer docked below. A chat over several papers
 * shows each paper's summary from its chip instead (ARA-088).
 */
export function ConversationThread({ paper, chat, papers }: { paper: Paper; chat: ChatSummary; papers?: PaperSelection }) {
  const generation = useGenerationSettings()
  const stream = useChatStream(chat)
  const memory = useChatMemory(chat.id).data?.memory
  const [text, setText] = useState('')
  const local = generation.models.find((model) => model.key === generation.settings.model)?.provider === 'ollama'
  const gate = questionGate(paper, { usable: generation.usableFor('chat'), loading: generation.loading, pdfComing: usePdfComing(paper), localForSeveral: local && chat.papers.length > 1 })
  const loaded = stream.history.isSuccess
  const ready = canAsk(gate) && loaded && !stream.busy

  const { saved, draft, pending } = stream
  const progress = stream.streaming && stream.stage ? stageLabels[stream.stage] : null
  const asked = saved.filter((message) => message.role === 'user').length
  // While streaming, the live draft stands in for its saved row; the optimistic question shows until saved.
  const rows = draft ? saved.map((message) => (message.id === draft.id ? draft : message)) : saved
  const question = pending && asked <= pending.baseline ? pending.text : null
  const unsavedDraft = draft && !saved.some((message) => message.id === draft.id) ? draft : null
  const empty = loaded && !rows.length && !question && !unsavedDraft && !stream.streaming && !peekQuestion(chat.id)
  const cited = useMemo(() => [...saved, ...(draft ? [draft] : [])].flatMap((message) => message.citations), [saved, draft])
  const sources = useChatSources(chat.papers, cited)
  const several = chat.papers.length > 1
  const { scrollRef, onScroll, away, scrolled, stick, toLatest } = useFollowBottom(`${rows.length}:${question ?? ''}:${draft?.id ?? ''}:${draft?.content.length ?? 0}:${draft?.state ?? ''}`)

  function ask(content: string, settings: GenerationSettings = generation.settings, requestId?: string) {
    stick()
    setText('')
    void stream.send(content, settings, requestId)
  }

  // Opening a chat adopts the model and effort of its latest answer once, never as a saved default.
  const restored = useRef(false)
  const restore = useEffectEvent(() => {
    restored.current = true
    const next = restoreChatSettings(generation.models, stream.saved)
    if (next) generation.setSettings(next)
  })
  useEffect(() => {
    if (loaded && !generation.loading && !restored.current) restore()
  }, [loaded, generation.loading])

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
    : chat.papers.some((item) => item.paper_id === paper.id && item.document_id !== paper.active_document_id) ? 'This conversation uses an earlier PDF of this paper.'
    : memory ? <MemoryNote memory={memory} /> : null

  return (
    <ThreadLayout
      scrollRef={scrollRef}
      onScroll={onScroll}
      away={away}
      scrolled={scrolled}
      onLatest={toLatest}
      composer={
        <ConversationComposer
          chatId={chat.id}
          value={text}
          onValueChange={setText}
          onSubmit={() => { if (ready) ask(text) }}
          gate={gate}
          sendable={loaded}
          busy={stream.busy}
          onStop={stream.streaming ? stream.stop : undefined}
          note={note}
          papers={papers}
        />
      }
    >
      {!several && <SummaryCard paper={paper} />}
      {stream.history.isPending && <HistorySkeleton />}
      <ErrorNotice error={stream.history.error} retry={() => void stream.history.refetch()} />
      {empty && ready && <SuggestedQuestions onSelect={ask} />}
      {rows.map((message) => message.role === 'user'
        ? <UserMessage key={message.id} content={message.content} />
        : <AssistantMessage key={message.id} message={message} sources={sources} progress={message.id === draft?.id ? progress : null} />)}
      {question && <UserMessage content={question} />}
      {unsavedDraft && <AssistantMessage message={unsavedDraft} sources={sources} progress={progress} />}
      {stream.streaming && !draft && <PendingAnswer />}
      <ErrorNotice error={stream.error} />
      <p role="status" className="sr-only">{stream.streaming ? progress ?? 'Assistant is responding.' : stream.outcome ? announcements[stream.outcome] : ''}</p>
    </ThreadLayout>
  )
}
