import { useEffect } from 'react'
import { Navigate } from 'react-router-dom'
import { toast } from 'sonner'
import type { Paper } from '@/api/types'

/**
 * A link to an upload that joined a library paper answers with that paper (ARA-086): open it at its own address and
 * say why, once.
 */
export function JoinedRedirect({ paper }: { paper: Paper }) {
  useEffect(() => { toast(`This PDF matched “${paper.title || 'Untitled paper'}” in your library, so it was added there.`, { id: `joined-${paper.id}` }) }, [paper.id, paper.title])
  return <Navigate to={`/papers/${paper.id}`} replace />
}
