import { useState } from 'react'
import type { Paper } from '@/api/types'
import { emptyDraft, withoutPaper, type Draft, type DraftMention } from '@/lib/mentions'

type Chosen = { paper: Paper; explicit: boolean }

/**
 * A first question and the papers it asks about, before its chat exists (ARA-096): papers added with the @ button,
 * shown as chips, plus papers its pills mention. A paper only pills brought in leaves with its last pill, and removing
 * a paper also removes its pills. With `fallback`, the question always asks about at least that paper.
 */
export function useDraftPapers({ initial = [], fallback }: { initial?: Paper[]; fallback?: Paper } = {}) {
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  // Every paper chosen or mentioned so far, in order; a deleted pill's paper is kept so undo brings it back.
  const [chosen, setChosen] = useState<Chosen[]>(() => initial.map((paper) => ({ paper, explicit: true })))
  const pills = new Set(draft.mentions.map((mention) => mention.paper_id))
  const attached = chosen.filter((item) => item.explicit || pills.has(item.paper.id)).map((item) => item.paper)
  const papers = attached.length || !fallback ? attached : [fallback]
  const include = (paper: Paper, explicit: boolean) => setChosen((current) => current.some((item) => item.paper.id === paper.id)
    ? current.map((item) => (item.paper.id === paper.id ? { ...item, explicit: item.explicit || explicit } : item))
    : [...current, { paper, explicit }])
  const remove = (paper: Pick<Paper, 'id'>) => {
    setChosen((current) => current.map((item) => (item.paper.id === paper.id ? { ...item, explicit: false } : item)))
    setDraft((current) => withoutPaper(current, paper.id))
  }
  return {
    draft,
    setDraft,
    onDraftChange: (text: string, mentions: DraftMention[]) => setDraft({ text, mentions }),
    papers,
    /** A paper picked after typing @: chosen while a pill mentions it. */
    mentioned: (paper: Paper) => include(paper, false),
    /** The @ button: adds a paper, or removes a chosen one with its pills. */
    toggle: (paper: Paper) => (papers.some((item) => item.id === paper.id) ? remove(paper) : include(paper, true)),
    remove,
  }
}
