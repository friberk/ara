import type { Paper } from '@/api/types'
import { ChatPanel } from '@/components/ChatPanel'
import { SummaryPanel } from '@/components/SummaryPanel'
import { useGenerationSettings } from '@/components/composer/generation-settings'

export type ConversationPaneProps = {
  paper: Paper
  /** The chat in the URL (/papers/:paperId/chats/:chatId); undefined shows a new-conversation start. */
  chatId?: string
}

/**
 * Contract stub (lead): legacy summary and chat panels. ARA-036 replaces it with the chat-first pane:
 * summary card first, streaming thread, docked composer with model switcher, chat switcher.
 * Inside the workspace it may call useWorkspace().showSource(citation) for citation chips.
 */
export function ConversationPane({ paper }: ConversationPaneProps) {
  const generation = useGenerationSettings()
  const ready = paper.document_status === 'ready' && !!paper.active_document_id
  return (
    <div className="grid gap-6 p-4">
      <SummaryPanel paper={paper} settings={generation.settings} allowed={ready && generation.usableFor('summary')} />
      <ChatPanel paper={paper} settings={generation.settings} allowed={ready && generation.usableFor('chat')} />
    </div>
  )
}
