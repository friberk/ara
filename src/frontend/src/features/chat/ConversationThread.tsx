import { useEffect, useEffectEvent, useMemo, useRef, useState } from 'react'
import type { ChatSummary, GenerationSettings, Paper, RetrievalStage } from '@/api/types'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { restoreChatSettings } from '@/components/composer/reasoning'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { Skeleton } from '@/components/ui/skeleton'
import { SummaryCard } from '@/features/summary'
import { useChatMemory } from '@/hooks/queries/retrieval'
import { emptyDraft, mentionedPapers, withoutPaper, type Draft } from '@/lib/mentions'
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
const stageLabels: Record<RetrievalStage, string> = { waiting: 'Waiting for the local model…', planning: 'Searching the paper…', retrieving: 'Searching the paper…', reranking: 'Searching the paper…', generating: 'Writing the answer…', widening: 'Searching more widely…', mapping: 'Reading each paper…' }

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
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  // A paper removed from the chat takes its pills out of the draft, which would otherwise add it back (ARA-096).
  const included = chat.papers.map((item) => item.paper_id)
  const [previous, setPrevious] = useState(included)
  if (previous.join() !== included.join()) {
    setPrevious(included)
    const removed = previous.filter((id) => !included.includes(id))
    if (removed.length) setDraft((current) => removed.reduce(withoutPaper, current))
  }
  const local = generation.models.find((model) => model.key === generation.settings.model)?.provider === 'ollama'
  // Papers the draft mentions join the chat when it is sent.
  const severalOnSend = new Set([...included, ...mentionedPapers(draft.mentions)]).size > 1
  const removed = chat.papers.some((item) => item.pdf_removed) ? (chat.papers.length > 1 ? 'one of several' : 'only') : undefined
  const gate = questionGate(paper, { usable: generation.usableFor('chat'), loading: generation.loading, pdfComing: usePdfComing(paper), localForSeveral: local && severalOnSend, pdfRemoved: removed })
  const loaded = stream.history.isSuccess
  const ready = canAsk(gate) && loaded && !stream.busy

  const { saved, draft: answer, pending } = stream
  const progress = stream.streaming && stream.stage ? stageLabels[stream.stage] : null
  const asked = saved.filter((message) => message.role === 'user').length
  // While streaming, the live draft stands in for its saved row; the optimistic question shows until saved.
  const rows = answer ? saved.map((message) => (message.id === answer.id ? answer : message)) : saved
  const question = pending && asked <= pending.baseline ? pending : null
  const unsavedDraft = answer && !saved.some((message) => message.id === answer.id) ? answer : null
  const empty = loaded && !rows.length && !question && !unsavedDraft && !stream.streaming && !peekQuestion(chat.id)
  const cited = useMemo(() => [...saved, ...(answer ? [answer] : [])].flatMap((message) => message.citations), [saved, answer])
  const sources = useChatSources(chat.papers, cited)
  const several = chat.papers.length > 1
  const { scrollRef, onScroll, away, scrolled, stick, toLatest } = useFollowBottom(`${rows.length}:${question?.text ?? ''}:${answer?.id ?? ''}:${answer?.content.length ?? 0}:${answer?.state ?? ''}`)

  function ask(next: Draft, settings: GenerationSettings = generation.settings, requestId?: string) {
    stick()
    setDraft(emptyDraft)
    void stream.send(next, settings, requestId)
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
    const next = { text: queued.content, mentions: queued.mentions }
    if (gate.locked || stream.busy) setDraft(next)
    else ask(next, queued.settings, queued.request_id)
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
          draft={draft}
          onDraftChange={(text, mentions) => setDraft({ text, mentions })}
          onSubmit={() => { if (ready) ask(draft) }}
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
      {empty && ready && <SuggestedQuestions onSelect={(text) => ask({ text, mentions: [] })} />}
      {rows.map((message) => message.role === 'user'
        ? <UserMessage key={message.id} content={message.content} mentions={message.mentions} />
        : <AssistantMessage key={message.id} message={message} sources={sources} progress={message.id === answer?.id ? progress : null} />)}
      {question && <UserMessage content={question.text} mentions={question.mentions} />}
      {unsavedDraft && <AssistantMessage message={unsavedDraft} sources={sources} progress={progress} />}
      {stream.streaming && !answer && <PendingAnswer />}
      <ErrorNotice error={stream.error} />
      <p role="status" className="sr-only">{stream.streaming ? progress ?? 'Assistant is responding.' : stream.outcome ? announcements[stream.outcome] : ''}</p>
    </ThreadLayout>
  )
}
