import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import type { ChatSummary, Collection, Paper } from '@/api/types'
import { PaperChips } from '@/components/composer/PaperPicker'
import { useDraftPapers } from '@/components/composer/use-draft-papers'
import { chatHref } from '@/components/shell/recent-items'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { SummaryCard } from '@/features/summary'
import { useCreateChat } from '@/hooks/queries/chats'
import { trimDraft, type Draft } from '@/lib/mentions'
import { queueQuestion } from '@/lib/pending-questions'
import { usePdfComing } from '@/hooks/queries/uploads'
import { ConversationComposer } from './ConversationComposer'
import { canAsk, questionGate } from './question-gate'
import { SuggestedQuestions } from './SuggestedQuestions'
import { ThreadLayout } from './ThreadLayout'
import { asChatSummary, paperChatsKey } from './use-paper-chats'
import { useFollowBottom } from './use-follow-bottom'

/**
 * A conversation that does not exist yet. The first question creates the chat, queues itself for the
 * thread and opens /papers/:paperId/chats/:chatId, so no empty chats are left behind. The @ button adds more library
 * papers before the first question (ARA-088), and so do the question's pills while they mention them (ARA-096).
 */
export function NewConversation({ paper }: { paper: Paper }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const generation = useGenerationSettings()
  const create = useCreateChat()
  const { draft, onDraftChange, papers: chosen, mentioned, toggle, remove } = useDraftPapers({ initial: [paper], fallback: paper })
  const { scrollRef, onScroll, away, scrolled, toLatest } = useFollowBottom('start')
  const gate = questionGate(paper, { usable: generation.usableFor('chat'), loading: generation.loading, pdfComing: usePdfComing(paper) })
  const ready = canAsk(gate) && !create.isPending

  function ask(asked: Draft) {
    const { text: question, mentions } = trimDraft(asked)
    if (!question || !ready) return
    const settings = generation.settings
    create.mutate({ paperIds: chosen.map((item) => item.id) }, {
      onSuccess: (chat) => {
        // Seed the switcher so the thread opens at once; the list refetch then brings the server's title.
        client.setQueryData<Collection<ChatSummary>>(paperChatsKey(chat.paper_id), (previous) => ({ items: [asChatSummary(chat), ...(previous?.items ?? []).filter((item) => item.id !== chat.id)] }))
        queueQuestion(chat.id, { content: question, mentions, settings })
        navigate(chatHref(chat))
      },
    })
  }

  return (
    <ThreadLayout
      scrollRef={scrollRef}
      onScroll={onScroll}
      away={away}
      scrolled={scrolled}
      onLatest={toLatest}
      composer={
        <ConversationComposer
          draft={draft}
          onDraftChange={onDraftChange}
          onSubmit={() => ask(draft)}
          gate={gate}
          sendable={!create.isPending}
          busy={create.isPending}
          papers={{
            selected: chosen.map((item) => item.id),
            onSelect: toggle,
            onMentioned: mentioned,
            header: chosen.length > 1 && <PaperChips papers={chosen} onRemove={remove} />,
          }}
        />
      }
    >
      <SummaryCard paper={paper} />
      {ready && <SuggestedQuestions onSelect={(text) => ask({ text, mentions: [] })} />}
      <ErrorNotice error={create.error} />
    </ThreadLayout>
  )
}
