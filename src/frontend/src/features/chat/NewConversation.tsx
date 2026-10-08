import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import type { ChatSummary, Collection, Paper } from '@/api/types'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { SummaryCard } from '@/features/summary'
import { useCreateChat } from '@/hooks/queries/chats'
import { queueQuestion } from '@/lib/pending-questions'
import { ConversationComposer } from './ConversationComposer'
import { canAsk, questionGate } from './question-gate'
import { SuggestedQuestions } from './SuggestedQuestions'
import { ThreadLayout } from './ThreadLayout'
import { asChatSummary, paperChatsKey } from './use-paper-chats'
import { useFollowBottom } from './use-follow-bottom'

/**
 * A conversation that does not exist yet. The first question creates the chat, queues itself for the
 * thread and opens /papers/:paperId/chats/:chatId, so no empty chats are left behind.
 */
export function NewConversation({ paper }: { paper: Paper }) {
  const navigate = useNavigate()
  const client = useQueryClient()
  const generation = useGenerationSettings()
  const create = useCreateChat(paper.id)
  const [text, setText] = useState('')
  const { scrollRef, onScroll, away, toLatest } = useFollowBottom('start')
  const gate = questionGate(paper, { usable: generation.usableFor('chat'), loading: generation.loading })
  const ready = canAsk(gate) && !create.isPending

  function ask(content: string) {
    const question = content.trim()
    if (!question || !ready) return
    const settings = generation.settings
    create.mutate(undefined, {
      onSuccess: (chat) => {
        // Seed the switcher so the thread opens at once; the list refetch then brings the server's title.
        client.setQueryData<Collection<ChatSummary>>(paperChatsKey(paper.id), (previous) => ({ items: [asChatSummary(chat, paper.title), ...(previous?.items ?? []).filter((item) => item.id !== chat.id)] }))
        queueQuestion(chat.id, { content: question, settings })
        navigate(`/papers/${paper.id}/chats/${chat.id}`)
      },
    })
  }

  return (
    <ThreadLayout
      scrollRef={scrollRef}
      onScroll={onScroll}
      away={away}
      onLatest={toLatest}
      composer={<ConversationComposer value={text} onValueChange={setText} onSubmit={() => ask(text)} gate={gate} sendable={!create.isPending} busy={create.isPending} />}
    >
      <SummaryCard paper={paper} />
      <SuggestedQuestions disabled={!ready} onSelect={ask} />
      <ErrorNotice error={create.error} />
    </ThreadLayout>
  )
}
