import { Extension, type Editor, type JSONContent, type Range } from '@tiptap/core'
import Document from '@tiptap/extension-document'
import HardBreak from '@tiptap/extension-hard-break'
import Mention from '@tiptap/extension-mention'
import Paragraph from '@tiptap/extension-paragraph'
import Text from '@tiptap/extension-text'
import { Placeholder, UndoRedo } from '@tiptap/extensions'
import { Fragment, Slice, type DOMOutputSpec, type Node as ProseMirrorNode } from '@tiptap/pm/model'
import { Plugin, PluginKey, Selection, type EditorState } from '@tiptap/pm/state'
import type { EditorView } from '@tiptap/pm/view'
import { exitSuggestion } from '@tiptap/suggestion'
import { pillClass, pillIconClass, pillLabelClass } from '@/components/paper/pill'
import { codePoints, type Draft, type DraftMention } from '@/lib/mentions'
import { cn } from '@/lib/utils'

/** A paper as a pill: its id, its label ("Karpukhin 2020") and the citation that names it for screen readers. */
export type PaperPill = { id: string; label: string; citation: string }
/** What typing @ hands the paper picker: insert a pill where @ was typed, or put the caret back after it. */
export type Mention = { refocus: () => void; insert: (pill: PaperPill) => void }

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
const svg = 'http://www.w3.org/2000/svg'
// lucide-react's FileText, the icon every paper chip uses; the history pill renders the React icon.
const fileText = ['M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z', 'M14 2v4a2 2 0 0 0 2 2h4', 'M10 9H8', 'M16 13H8', 'M16 17H8']

function pillDom(attributes: Record<string, unknown>, label: string, citation: string | null): DOMOutputSpec {
  const icon: DOMOutputSpec = [
    `${svg} svg`,
    { width: '24', height: '24', viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', 'stroke-width': '2', 'stroke-linecap': 'round', 'stroke-linejoin': 'round', class: `lucide lucide-file-text ${pillIconClass}`, 'aria-hidden': 'true' },
    ...fileText.map((d): DOMOutputSpec => [`${svg} path`, { d }]),
  ]
  return ['span', { ...attributes, class: pillClass, role: 'img', 'aria-roledescription': 'paper', 'aria-label': citation || label }, icon, ['span', { class: pillLabelClass }, label]]
}

/** The official Mention node with a citation attribute; its text is its label, so the question reads naturally. */
const PaperMention = Mention.extend({
  addAttributes() {
    return { ...this.parent?.(), citation: { default: null, renderHTML: () => ({}), parseHTML: (element) => element.getAttribute('aria-label') } }
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
        mentions.push({ paper_id: String(node.attrs.id), label, start: at, end: at + codePoints(label).length, ...(node.attrs.citation ? { citation: String(node.attrs.citation) } : {}) })
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
    content.push(...lines(chars.slice(at, mention.start).join('')), { type: 'mention', attrs: { id: mention.paper_id, label: mention.label, citation: mention.citation ?? null } })
    at = mention.end
  }
  content.push(...lines(chars.slice(at).join('')))
  return { type: 'doc', content: [{ type: 'paragraph', content }] }
}

/** The key that tells whether a draft from outside differs from what the editor last reported. */
export const draftKey = (draft: Draft) => JSON.stringify([draft.text, draft.mentions.map((item) => [item.paper_id, item.label, item.start, item.end])])

const length = (doc: ProseMirrorNode) => codePoints(toDraft(doc).text).length

/** Replaces the typed @ (and the space after it, if any) with a pill and one space; nothing changes if it would overflow. */
function insertPill(editor: Editor, range: Range, pill: PaperPill) {
  const { doc } = editor.state
  const typed = range.to <= doc.content.size && doc.textBetween(range.from, range.to).startsWith('@')
  const at = typed ? { ...range } : { from: editor.state.selection.from, to: editor.state.selection.to }
  if (doc.textBetween(at.to, Math.min(at.to + 1, doc.content.size)) === ' ') at.to += 1
  editor.chain().focus().insertContentAt(at, [{ type: 'mention', attrs: { id: pill.id, label: pill.label, citation: pill.citation } }, { type: 'text', text: ' ' }]).run()
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
      renderHTML: ({ options, node }) => pillDom(options.HTMLAttributes, String(node.attrs.label ?? ''), node.attrs.citation),
      suggestion: {
        pluginKey: mentionKey,
        allowedPrefixes: [' ', ' '],
        allow: ({ editor, state }) => settingsOf(state).mentionable && editor.view.hasFocus(),
        render: () => ({
          onStart: ({ editor, range }) => editor.emit('composerMention', {
            insert: (pill) => insertPill(editor, range, pill),
            // A picker closed without a pick leaves the @ as text, so typing on does not reopen it.
            refocus: () => { exitSuggestion(editor.view, mentionKey); editor.commands.focus() },
          }),
        }),
      },
    }),
    Keys,
  ]
}
