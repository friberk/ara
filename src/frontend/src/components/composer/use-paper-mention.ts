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
  // Whether a picker is open right now, without waiting for a render: the close of one picker can land after the next
  // @ has opened another, and must not dismiss it.
  const live = useRef(false)
  const show = (next: boolean) => { live.current = next; setOpen(next) }
  const [typed, setTyped] = useState<Mention | undefined>(undefined)
  const [picked, setPicked] = useState(false)
  return {
    target,
    onMention: (handle: Mention) => { setTyped(handle); setPicked(false); show(true) },
    picker: {
      open,
      selected,
      mentioning: !!typed,
      onOpenChange: (next: boolean) => { if (next) setPicked(false); show(next) },
      onSelect: (paper: Paper) => {
        const pill = paperPill(paper)
        if (typed) typed.insert(pill)
        else target.current?.insert(pill)
        setPicked(true)
      },
      // After a pick, or a picker opened by typing @, the caret goes back to the question; otherwise to the button. A
      // close that lands after a new @ has reopened the picker belongs to the earlier session and changes nothing.
      refocus: typed || picked ? () => {
        if (live.current) return
        if (typed) typed.refocus()
        else target.current?.focus()
        setTyped(undefined)
      } : undefined,
    },
  }
}
