import { Extension, type Editor, type JSONContent, type Range } from '@tiptap/core'
import Document from '@tiptap/extension-document'
import HardBreak from '@tiptap/extension-hard-break'
import Mention from '@tiptap/extension-mention'
import Paragraph from '@tiptap/extension-paragraph'
import Text from '@tiptap/extension-text'
import { Placeholder, UndoRedo } from '@tiptap/extensions'
import { Fragment, Slice, type Node as ProseMirrorNode } from '@tiptap/pm/model'
import { Plugin, PluginKey, Selection, type EditorState } from '@tiptap/pm/state'
import type { EditorView } from '@tiptap/pm/view'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { exitSuggestion } from '@tiptap/suggestion'
import type { PillPaper } from '@/components/paper/PaperPill'
import { codePoints, type Draft, type DraftMention } from '@/lib/mentions'
import { cn } from '@/lib/utils'
import { MentionView } from './MentionView'

/** A paper as a pill: its id, its label (the title, which the question carries as text) and its citation details. */
export type PaperPill = { id: string; label: string; paper: PillPaper }
/** What typing @ hands the paper picker: insert a pill where @ was typed, or put the caret back after it. */
export type Mention = { refocus: () => void; insert: (pill: PaperPill) => void }
/** What the @ button hands the paper picker: insert a pill at the caret, or at the end when the question had no focus. */
export type MentionTarget = { insert: (pill: PaperPill) => void; focus: () => void }

/** The composer's props that the editor, created once, reads from its state; `configure` updates them. */
export type ComposerSettings = { label: string; placeholder: string; disabled: boolean; size: 'default' | 'large'; limit: number; mentionable: boolean }

declare module '@tiptap/core' {
  interface EditorEvents {
    /** Enter without Shift in the composer (ARA-096). */
    composerSubmit: []
    /** @ typed at the start of a word, with a handle to insert a pill there or return the caret. */
    composerMention: Mention
  }
}

const settingsKey = new PluginKey<ComposerSettings>('composer-settings')
const settingsOf = (state: EditorState) => settingsKey.getState(state)!
const mentionKey = new PluginKey('paper-mention')
/** Marks a draft set by the composer's owner (cleared after sending, restored from a queue): never limited, never undone. */
const fromOutside = 'composer-from-outside'

/**
 * The official Mention node, drawn by the shared paper pill (MentionView) and selectable, so a click, a tap or the
 * arrow keys select it whole. It keeps the paper's citation details for its card; its text is its label.
 */
const PaperMention = Mention.extend({
  selectable: true,
  addAttributes() {
    return { ...this.parent?.(), paper: { default: null, renderHTML: () => ({}), parseHTML: () => null } }
  },
  addNodeView() {
    return ReactNodeViewRenderer(MentionView, { as: 'span' })
  },
})

/** The question a document holds: hard breaks and paragraphs become line breaks, pills their labels at code-point spans. */
export function toDraft(doc: ProseMirrorNode): Draft {
  let text = ''
  let at = 0
  const mentions: DraftMention[] = []
  const add = (part: string) => { text += part; at += codePoints(part).length }
  doc.forEach((block, _offset, index) => {
    if (index > 0) add('\n')
    block.forEach((node) => {
      if (node.isText) add(node.text ?? '')
      else if (node.type.name === 'hardBreak') add('\n')
      else if (node.type.name === 'mention') {
        const label = String(node.attrs.label ?? '')
        mentions.push({ paper_id: String(node.attrs.id), label, start: at, end: at + codePoints(label).length, ...(node.attrs.paper ? { paper: node.attrs.paper as PillPaper } : {}) })
        add(label)
      }
    })
  })
  return { text, mentions }
}

const lines = (text: string): JSONContent[] => text.split('\n').flatMap((line, index) => [...(index ? [{ type: 'hardBreak' }] : []), ...(line ? [{ type: 'text', text: line }] : [])])

/** A draft as editor content; a pill whose span does not match the text stays text. */
export function toContent(draft: Draft): JSONContent {
  const chars = codePoints(draft.text)
  const content: JSONContent[] = []
  let at = 0
  for (const mention of draft.mentions) {
    if (mention.start < at || chars.slice(mention.start, mention.end).join('') !== mention.label) continue
    content.push(...lines(chars.slice(at, mention.start).join('')), { type: 'mention', attrs: { id: mention.paper_id, label: mention.label, paper: mention.paper ?? null } })
    at = mention.end
  }
  content.push(...lines(chars.slice(at).join('')))
  return { type: 'doc', content: [{ type: 'paragraph', content }] }
}

/** The key that tells whether a draft from outside differs from what the editor last reported. */
export const draftKey = (draft: Draft) => JSON.stringify([draft.text, draft.mentions.map((item) => [item.paper_id, item.label, item.start, item.end])])

const length = (doc: ProseMirrorNode) => codePoints(toDraft(doc).text).length

/**
 * Puts a pill in place of `at` (the typed @, or the selection) followed by one space, reusing a space already there and
 * adding one before it when the pill would touch a word. Nothing changes if it would pass the limit.
 */
function insertPill(editor: Editor, at: Range, pill: PaperPill) {
  const { doc } = editor.state
  const range = { ...at }
  if (doc.textBetween(range.to, Math.min(range.to + 1, doc.content.size)) === ' ') range.to += 1
  const before = range.from > 1 ? doc.textBetween(range.from - 1, range.from, '\n', '\n') : ''
  const pad = before && !/\s/.test(before) ? [{ type: 'text', text: ' ' }] : []
  editor.chain().focus().insertContentAt(range, [...pad, { type: 'mention', attrs: { id: pill.id, label: pill.label, paper: pill.paper } }, { type: 'text', text: ' ' }]).run()
  // TipTap focuses on the next frame; typing straight after a pick must already reach the question.
  if (!editor.isDestroyed) editor.view.focus()
}

/** A pill where @ was typed, or at the caret if the document changed since. */
function insertForTyped(editor: Editor, range: Range, pill: PaperPill) {
  const { doc, selection } = editor.state
  const typed = range.to <= doc.content.size && doc.textBetween(range.from, range.to).startsWith('@')
  insertPill(editor, typed ? range : { from: selection.from, to: selection.to }, pill)
}

/** A pill from the @ button: at the caret when the question had focus before the button took it, else at the end. */
export function insertAtCaret(editor: Editor, pill: PaperPill, atCaret: boolean) {
  const { selection, doc } = editor.state
  const end = Selection.atEnd(doc).from
  insertPill(editor, atCaret ? { from: selection.from, to: selection.to } : { from: end, to: end }, pill)
}

/** Pasted text arrives as plain text with line breaks, cut to the room left under the limit. */
function pastePlain(view: EditorView, text: string, limit: number) {
  const { state } = view
  const room = Math.max(0, limit - length(state.tr.deleteSelection().doc))
  const kept = codePoints(text.replace(/\r\n?/g, '\n')).slice(0, room).join('')
  const nodes = kept.split('\n').flatMap((line, index) => [...(index ? [state.schema.nodes.hardBreak!.create()] : []), ...(line ? [state.schema.text(line)] : [])])
  view.dispatch(state.tr.replaceSelection(new Slice(Fragment.from(nodes), 0, 0)).scrollIntoView())
}

export function configure(editor: Editor, settings: ComposerSettings) {
  editor.view.dispatch(editor.state.tr.setMeta(settingsKey, settings).setMeta('addToHistory', false))
}

/** Sets a draft from outside the editor, with the caret at its end. */
export function setDraft(editor: Editor, draft: Draft) {
  editor.chain()
    .command(({ tr }) => { tr.setMeta(fromOutside, true).setMeta('addToHistory', false); return true })
    .setContent(toContent(draft), { emitUpdate: false })
    .command(({ tr }) => { tr.setSelection(Selection.atEnd(tr.doc)); return true })
    .run()
}

/**
 * The composer's editor: one paragraph of text, line breaks and paper pills (ARA-096). Enter sends and Shift+Enter
 * adds a line; Backspace or Delete next to a pill removes it whole; @ at the start of a word asks for a paper.
 */
export function composerExtensions(initial: ComposerSettings) {
  const Keys = Extension.create({
    name: 'composerKeys',
    priority: 1000,
    addKeyboardShortcuts() {
      return {
        Delete: ({ editor }) => editor.commands.command(({ tr, state }) => {
          const after = state.selection.empty ? state.selection.$from.nodeAfter : null
          if (after?.type.name !== 'mention') return false
          tr.delete(state.selection.from, state.selection.from + after.nodeSize)
          return true
        }),
      }
    },
    addProseMirrorPlugins() {
      const { editor } = this
      return [
        new Plugin<ComposerSettings>({
          key: settingsKey,
          state: { init: () => initial, apply: (tr, settings) => tr.getMeta(settingsKey) ?? settings },
          // Like a textarea's maxLength: changes that would pass the limit are refused whole, so a pill is never cut.
          filterTransaction: (tr, state) => !tr.docChanged || !!tr.getMeta(fromOutside) || length(tr.doc) <= settingsOf(state).limit || length(tr.doc) <= length(state.doc),
          props: {
            attributes: (state) => {
              const { label, placeholder, disabled, size } = settingsOf(state)
              return {
                role: 'textbox',
                'aria-multiline': 'true',
                'aria-label': label,
                'aria-placeholder': placeholder,
                'aria-disabled': String(disabled),
                class: cn(
                  'composer-editor max-h-60 w-full overflow-y-auto bg-transparent px-4 pt-3.5 pb-1 text-[15px] leading-6 break-words whitespace-pre-wrap outline-none focus-visible:outline-none aria-disabled:cursor-not-allowed',
                  size === 'large' ? 'min-h-16' : 'min-h-11',
                ),
              }
            },
            handleKeyDown: (view, event) => {
              if (event.key !== 'Enter' || event.shiftKey || event.isComposing || view.composing) return false
              event.preventDefault()
              editor.emit('composerSubmit')
              return true
            },
            handlePaste: (view, event) => {
              pastePlain(view, event.clipboardData?.getData('text/plain') ?? '', settingsOf(view.state).limit)
              return true
            },
          },
        }),
      ]
    },
  })
  return [
    Document,
    Paragraph,
    Text,
    HardBreak,
    UndoRedo,
    Placeholder.configure({ placeholder: ({ editor }) => settingsOf(editor.state).placeholder, showOnlyWhenEditable: false }),
    PaperMention.configure({
      deleteTriggerWithBackspace: true,
      renderText: ({ node }) => String(node.attrs.label ?? ''),
      renderHTML: ({ options, node }) => ['span', options.HTMLAttributes, String(node.attrs.label ?? '')],
      suggestion: {
        pluginKey: mentionKey,
        allowedPrefixes: [' ', ' '],
        allow: ({ editor, state }) => settingsOf(state).mentionable && editor.isFocused,
        render: () => ({
          onStart: ({ editor, range }) => editor.emit('composerMention', {
            insert: (pill) => insertForTyped(editor, range, pill),
            // A picker closed without a pick leaves the @ as text, so typing on does not reopen it.
            refocus: () => { exitSuggestion(editor.view, mentionKey); editor.commands.focus() },
          }),
        }),
      },
    }),
    Keys,
  ]
}
