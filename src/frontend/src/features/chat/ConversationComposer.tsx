import { Composer } from '@/components/composer/Composer'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { ModelSwitcher } from '@/components/composer/ModelSwitcher'
import { ContextMeter } from './ContextMeter'
import type { QuestionGate } from './question-gate'

const defaultNote = 'Answers come from this paper’s PDF and cite their pages. Check important claims against the source.'

/** The docked question composer. Its footnote explains whatever is keeping a question from being sent. */
export function ConversationComposer({ chatId, value, onValueChange, onSubmit, gate, sendable, busy, onStop, note }: {
  /** The chat whose context and cost the ring reports for the model selected here; a conversation not yet created has none. */
  chatId?: string
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
  const { settings } = useGenerationSettings()
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
      leading={chatId ? <ContextMeter chatId={chatId} settings={settings} /> : undefined}
      trailing={<ModelSwitcher purpose="chat" align="end" />}
      footnote={gate.reason ?? note ?? defaultNote}
    />
  )
}
