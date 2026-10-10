// Route elements for the conversation pane tests (components only, so fast refresh stays quiet).
import { useLocation, useParams } from 'react-router-dom'
import type { Paper } from '@/api/types'
import { ConversationPane } from '.'

export function PaneRoute({ value, others = [] }: { value: Paper; others?: Paper[] }) {
  const { paperId, chatId } = useParams()
  const shown = others.find((item) => item.id === paperId) ?? value
  return <ConversationPane key={shown.id} paper={shown} chatId={chatId} />
}
export function CurrentPath() { return <output aria-label="Current path">{useLocation().pathname}</output> }
