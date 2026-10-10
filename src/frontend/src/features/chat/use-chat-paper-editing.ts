import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import type { ChatSummary, Paper } from '@/api/types'
import { chatHref } from '@/components/shell/recent-items'
import { useChatPapers } from '@/hooks/queries/chats'

/**
 * Removing a chat's papers (ARA-088); papers join through a question's pills (ARA-096). When the paper in the URL leaves
 * the chat, the chat moves to its new first paper's address; a refused change says why. A removal offers Undo (ARA-110),
 * which adds the paper's current PDF back; an earlier PDF the chat had pinned is gone with its removal.
 */
export function useChatPaperEditing(chat: ChatSummary | undefined, paper: Paper) {
  const navigate = useNavigate()
  const { remove, restore } = useChatPapers(chat?.id ?? '')
  const failed = (error: Error) => toast.error(error.message)
  const removePaper = (paperId: string) => {
    const title = chat?.papers.find((item) => item.paper_id === paperId)?.title?.trim() || 'the paper'
    remove.mutate(paperId, {
      onSuccess: (updated) => {
        if (updated.paper_id !== paper.id) navigate(chatHref(updated), { replace: true })
        toast('Removed from this chat', {
          action: {
            label: 'Undo',
            onClick: () => restore.mutate(paperId, { onError: (error) => toast.error(`Couldn't put ${title} back in this chat. ${error.message}`) }),
          },
        })
      },
      onError: failed,
    })
  }
  const selected = chat?.papers.map((item) => item.paper_id) ?? []
  return {
    selected,
    removing: remove.isPending ? remove.variables : null,
    remove: removePaper,
  }
}
