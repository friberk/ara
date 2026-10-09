import { Composer } from '@/components/composer/Composer'
import { ModelSwitcher } from '@/components/composer/ModelSwitcher'
import type { QuestionGate } from './question-gate'

const defaultNote = 'Answers come from this paper’s PDF and cite their pages. Check important claims against the source.'

/** The docked question composer. Its footnote explains whatever is keeping a question from being sent. */
export function ConversationComposer({ value, onValueChange, onSubmit, gate, sendable, busy, onStop, note }: {
  value: string
  onValueChange: (value: string) => void
  onSubmit: () => void
  gate: QuestionGate
  /** False while something other than the gate blocks sending, such as history loading or a chat being created. */
  sendable: boolean
  busy: boolean
  onStop?: () => void
  note?: React.ReactNode
}) {
  return (
    <Composer
      value={value}
      onValueChange={onValueChange}
      onSubmit={onSubmit}
      label="Question about this paper"
      placeholder="Ask a question about this paper"
      submitLabel="Ask question"
      stopLabel="Stop generation"
      disabled={gate.locked}
      submitDisabled={!!gate.reason || gate.waiting || !sendable}
      busy={busy}
      onStop={onStop}
      trailing={<ModelSwitcher purpose="chat" align="end" />}
      footnote={gate.reason ?? note ?? defaultNote}
    />
  )
}
