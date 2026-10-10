import { useSyncExternalStore } from 'react'
import type { Editor } from '@tiptap/core'
import { NodeViewWrapper, type ReactNodeViewProps } from '@tiptap/react'
import { PaperPill, type PillPaper } from '@/components/paper/PaperPill'

function useFocused(editor: Editor) {
  return useSyncExternalStore(
    (changed) => {
      editor.on('focus', changed).on('blur', changed)
      return () => { editor.off('focus', changed).off('blur', changed) }
    },
    () => editor.isFocused,
  )
}

/** Removes a pill and the space typed after it, so no double space is left; the caret stays where it was. */
function removePill(editor: Editor, at: number, size: number) {
  editor.commands.command(({ tr }) => {
    const after = tr.doc.textBetween(at + size, Math.min(at + size + 1, tr.doc.content.size))
    tr.delete(at, at + size + (after === ' ' ? 1 : 0))
    return true
  })
}

/**
 * A mention in the composer (ARA-096): the shared paper pill, selected while the editor has a node selection on it and
 * focus, with its remove button. Removing it changes the draft as Backspace does, so attachments follow.
 */
export function MentionView({ node, selected, editor, getPos }: ReactNodeViewProps) {
  const focused = useFocused(editor)
  return (
    <NodeViewWrapper as="span">
      <PaperPill
        title={String(node.attrs.label ?? '')}
        paper={node.attrs.paper as PillPaper | null}
        selected={selected && focused}
        onRemove={() => {
          const at = getPos()
          if (at !== undefined) removePill(editor, at, node.nodeSize)
        }}
      />
    </NodeViewWrapper>
  )
}
