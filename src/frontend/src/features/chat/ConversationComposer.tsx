import { Composer } from '@/components/composer/Composer'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { ModelSwitcher } from '@/components/composer/ModelSwitcher'
import { PaperPicker } from '@/components/composer/PaperPicker'
import { usePaperMention } from '@/components/composer/use-paper-mention'
import type { Draft, DraftMention } from '@/lib/mentions'
import { ContextMeter } from './ContextMeter'
import type { QuestionGate } from './question-gate'

const defaultNote = 'Answers come from this paper’s PDF and cite their pages. Check important claims against the source.'
const severalNote = 'Answers come from these papers’ PDFs and cite their pages. Check important claims against the source.'

/** The papers a conversation asks about, which the @ picker shows as checked; typing @ or the @ button mentions one (ARA-096). */
export type PaperSelection = { selected: string[] }

/** The docked question composer. Its footnote explains whatever is keeping a question from being sent. */
export function ConversationComposer({ chatId, draft, onDraftChange, onSubmit, gate, sendable, busy, onStop, note, papers }: {
  /** The chat whose context and cost the ring reports for the model selected here; a conversation not yet created has none. */
  chatId?: string
  draft: Draft
  onDraftChange: (text: string, mentions: DraftMention[]) => void
  onSubmit: () => void
  gate: QuestionGate
  /** False while something other than the gate blocks sending, such as history loading or a chat being created. */
  sendable: boolean
  busy: boolean
  onStop?: () => void
  note?: React.ReactNode
  /** Typing @ or the picker button adds a library paper or removes an included one. */
  papers?: PaperSelection
}) {
  const { settings } = useGenerationSettings()
  const mention = usePaperMention({ selected: papers?.selected ?? [] })
  const several = (papers?.selected.length ?? 1) > 1
  return (
    <Composer
      value={draft.text}
      mentions={draft.mentions}
      onValueChange={onDraftChange}
      onSubmit={onSubmit}
      label={several ? 'Question about these papers' : 'Question about this paper'}
      placeholder={several ? 'Ask a question about these papers' : 'Ask a question about this paper'}
      submitLabel="Ask question"
      stopLabel="Stop generation"
      disabled={gate.locked}
      submitDisabled={!!gate.reason || gate.waiting || !sendable}
      busy={busy}
      onStop={onStop}
      onMention={papers ? mention.onMention : undefined}
      mentionTarget={mention.target}
      leading={
        <>
          {papers && <PaperPicker label="Mention a paper" disabled={gate.locked} {...mention.picker} />}
          {chatId && <ContextMeter chatId={chatId} settings={settings} />}
        </>
      }
      trailing={<ModelSwitcher purpose="chat" align="end" />}
      footnote={gate.reason ?? note ?? (several ? severalNote : defaultNote)}
    />
  )
}
