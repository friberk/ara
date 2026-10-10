import { useState } from 'react'
import type { Paper } from '@/api/types'
import { mentionName } from '@/lib/paper-names'
import type { Mention } from './Composer'

/**
 * The @ paper picker of every composer (ARA-088). Typing @ opens it to mention a paper: choosing one adds it when it is
 * not chosen yet and inserts "@Surname Year" where @ was typed, and it never removes a paper. The @ button opens the
 * same picker to add or remove: choosing a checked paper removes it.
 */
export function usePaperMention({ selected, onSelect }: { selected: readonly string[]; onSelect: (paper: Paper) => void }) {
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
        if (!mention) return onSelect(paper)
        if (!selected.includes(paper.id)) onSelect(paper)
        mention.insert(`@${mentionName(paper)} `)
      },
      // Closing a picker opened by typing @ returns the cursor to the question.
      refocus: mention && (() => { mention.refocus(); setMention(undefined) }),
    },
  }
}
