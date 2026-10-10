import type { UploadMatch } from '@/api/types'

export const matchTitle = (match: Pick<UploadMatch, 'title'>) => `“${match.title || 'Untitled paper'}”`
export const attachedNote = (match: UploadMatch) => (match.has_pdf ? `The PDF replaced the one on ${matchTitle(match)}.` : `The PDF was attached to ${matchTitle(match)}.`)
