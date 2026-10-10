import { useState } from 'react'
import type { Paper } from '@/api/types'
import { citationText, mentionName } from '@/lib/paper-names'
import type { Mention, PaperPill } from './Composer'

export const paperPill = (paper: Paper): PaperPill => ({ id: paper.id, label: mentionName(paper), citation: citationText(paper) })

/**
 * The @ paper picker of every composer. Typing @ opens it to mention a paper: the paper picked becomes a pill where @
 * was typed (ARA-096), and `onMentioned` hears of it; nothing is added or removed here. The @ button opens the same
 * picker to add or remove papers: `onToggle`.
 */
export function usePaperMention({ selected, onToggle, onMentioned }: { selected: readonly string[]; onToggle: (paper: Paper) => void; onMentioned?: (paper: Paper) => void }) {
  const [open, setOpen] = useState(false)
  const [mention, setMention] = useState<Mention | undefined>(undefined)
  return {
    onMention: (handle: Mention) => { setMention(handle); setOpen(true) },
    picker: {
      open,
      selected,
      mentioning: !!mention,
      onOpenChange: setOpen,
      onSelect: (paper: Paper) => {
        if (!mention) return onToggle(paper)
        onMentioned?.(paper)
        mention.insert(paperPill(paper))
      },
      // Closing a picker opened by typing @ returns the caret to the question.
      refocus: mention && (() => { mention.refocus(); setMention(undefined) }),
    },
  }
}
