import { useRef, useState } from 'react'
import type { Paper } from '@/api/types'
import { mentionLabel } from '@/lib/paper-names'
import type { Mention, MentionTarget, PaperPill } from './Composer'

export const paperPill = (paper: Paper): PaperPill => ({ id: paper.id, label: mentionLabel(paper), paper: { authors: paper.authors, year: paper.year, venue: paper.venue } })

/**
 * The @ paper picker of every composer (ARA-096). Typing @ opens it, and the paper picked becomes a pill where @ was
 * typed; the @ button opens it too, and the pill goes at the caret, or at the end when the question had no focus.
 * Pills are the attachments, so the picker never adds or removes anything itself. Pass `target` to the Composer.
 */
export function usePaperMention({ selected }: { selected: readonly string[] }) {
  const target = useRef<MentionTarget>(null)
  const [open, setOpen] = useState(false)
  const [typed, setTyped] = useState<Mention | undefined>(undefined)
  const [picked, setPicked] = useState(false)
  return {
    target,
    onMention: (handle: Mention) => { setTyped(handle); setPicked(false); setOpen(true) },
    picker: {
      open,
      selected,
      mentioning: !!typed,
      onOpenChange: (next: boolean) => { if (next) setPicked(false); setOpen(next) },
      onSelect: (paper: Paper) => {
        const pill = paperPill(paper)
        if (typed) typed.insert(pill)
        else target.current?.insert(pill)
        setPicked(true)
      },
      // After a pick, or a picker opened by typing @, the caret goes back to the question; otherwise to the button.
      refocus: typed || picked ? () => { if (typed) typed.refocus(); else target.current?.focus(); setTyped(undefined) } : undefined,
    },
  }
}
