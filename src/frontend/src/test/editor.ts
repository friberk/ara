import { act, fireEvent } from '@testing-library/react'
import type { Editor } from '@tiptap/core'
import { toDraft } from '@/components/composer/editor'

/** The TipTap editor behind a composer's textbox; ProseMirror keeps it on its DOM node (ARA-096). */
export function editorOf(element: HTMLElement): Editor {
  const editor = (element as HTMLElement & { editor?: Editor }).editor
  if (!editor) throw new Error('This element is not a composer editor.')
  return editor
}

/** What the composer would send: its text, with each pill as its label, and the pills. */
export const draftIn = (element: HTMLElement) => toDraft(editorOf(element).state.doc)
export const textIn = (element: HTMLElement) => draftIn(element).text
/** A contenteditable has no disabled attribute; the composer stops being editable instead. */
export const isEditable = (element: HTMLElement) => element.getAttribute('contenteditable') === 'true'

/** Puts the caret right after, or right before, the nth pill, as the arrow keys would in a browser. */
export function caretAt(element: HTMLElement, pill: number, side: 'after' | 'before' = 'after') {
  const editor = editorOf(element)
  const positions: number[] = []
  editor.state.doc.descendants((node, position) => { if (node.type.name === 'mention') positions.push(position) })
  const position = positions[pill]
  if (position === undefined) throw new Error(`The composer has no pill ${pill}.`)
  act(() => { editor.commands.setTextSelection(side === 'after' ? position + 1 : position) })
}

/**
 * Backspace right after, or Delete right before, the nth pill. The caret is placed and the key pressed in one step, so a
 * selectionchange jsdom still has queued from earlier typing cannot move the caret in between.
 */
export function deletePill(element: HTMLElement, pill: number, key: 'Backspace' | 'Delete' = 'Backspace') {
  caretAt(element, pill, key === 'Backspace' ? 'after' : 'before')
  fireEvent.keyDown(element, { key })
}
