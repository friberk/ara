import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import type { ChatSummary, Collection, Paper } from '@/api/types'
import { chatHref } from '@/components/shell/recent-items'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { SummaryCard } from '@/features/summary'
import { useCreateChat } from '@/hooks/queries/chats'
import { emptyDraft, mentionedPapers, trimDraft, type Draft } from '@/lib/mentions'
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
 * thread and opens /papers/:paperId/chats/:chatId, so no empty chats are left behind. Papers the question's pills
 * mention join this one (ARA-088, ARA-096).
 */
export function NewConversation({ paper }: { paper: Paper }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const generation = useGenerationSettings()
  const create = useCreateChat()
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  // This paper, then the papers the question's pills mention (ARA-096).
  const paperIds = [...new Set([paper.id, ...mentionedPapers(draft.mentions)])]
  const { scrollRef, onScroll, away, scrolled, toLatest } = useFollowBottom('start')
  const gate = questionGate(paper, { usable: generation.usableFor('chat'), loading: generation.loading, pdfComing: usePdfComing(paper) })
  const ready = canAsk(gate) && !create.isPending

  function ask(asked: Draft) {
    const { text: question, mentions } = trimDraft(asked)
    if (!question || !ready) return
    const settings = generation.settings
    create.mutate({ paperIds }, {
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
          onDraftChange={(text, mentions) => setDraft({ text, mentions })}
          onSubmit={() => ask(draft)}
          gate={gate}
          sendable={!create.isPending}
          busy={create.isPending}
          papers={{ selected: paperIds }}
        />
      }
    >
      <SummaryCard paper={paper} />
      {ready && <SuggestedQuestions onSelect={(text) => ask({ text, mentions: [] })} />}
      <ErrorNotice error={create.error} />
    </ThreadLayout>
  )
}
