import { useEffect, useRef, useState } from 'react'

const carriesFiles = (event: DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes('Files')

/**
 * Files dragged anywhere over the window, as in a file manager; the returned flag drives <DropOverlay>. Text and link
 * drags are left alone, and a drop a drop zone already handled (default prevented) is not taken twice.
 */
export function usePageDrop(onFiles: (files: File[]) => void) {
  const [dragging, setDragging] = useState(false)
  const latest = useRef(onFiles)
  useEffect(() => { latest.current = onFiles })
  useEffect(() => {
    let depth = 0
    const enter = (event: DragEvent) => { if (!carriesFiles(event)) return; event.preventDefault(); depth += 1; setDragging(true) }
    const over = (event: DragEvent) => { if (carriesFiles(event)) event.preventDefault() }
    const leave = (event: DragEvent) => { if (!carriesFiles(event)) return; depth = Math.max(0, depth - 1); if (!depth) setDragging(false) }
    const drop = (event: DragEvent) => {
      depth = 0
      setDragging(false)
      if (event.defaultPrevented || !carriesFiles(event)) return
      event.preventDefault()
      const files = Array.from(event.dataTransfer?.files ?? [])
      if (files.length) latest.current(files)
    }
    window.addEventListener('dragenter', enter)
    window.addEventListener('dragover', over)
    window.addEventListener('dragleave', leave)
    window.addEventListener('drop', drop)
    return () => {
      window.removeEventListener('dragenter', enter)
      window.removeEventListener('dragover', over)
      window.removeEventListener('dragleave', leave)
      window.removeEventListener('drop', drop)
    }
  }, [])
  return dragging
}
