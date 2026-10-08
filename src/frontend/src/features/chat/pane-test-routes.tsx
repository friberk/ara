// Route elements for the conversation pane tests (components only, so fast refresh stays quiet).
import { useLocation, useParams } from 'react-router-dom'
import type { Paper } from '@/api/types'
import { ConversationPane } from '.'

export function PaneRoute({ value }: { value: Paper }) {
  const { chatId } = useParams()
  return <ConversationPane paper={value} chatId={chatId} />
}
export function CurrentPath() { return <output aria-label="Current path">{useLocation().pathname}</output> }
