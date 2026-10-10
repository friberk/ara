import { useEffect, useEffectEvent, useRef, useState } from 'react'
import { ArrowUp, Square } from 'lucide-react'
import type { Editor } from '@tiptap/core'
import { EditorContent, useEditor } from '@tiptap/react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { DraftMention } from '@/lib/mentions'
import { cn } from '@/lib/utils'
import { composerExtensions, configure, draftKey, setDraft, toContent, toDraft, type Mention } from './editor'

export type { Mention, PaperPill } from './editor'

const noMentions: readonly DraftMention[] = []

export type ComposerProps = {
  /** The question's text; each pill appears in it as its label. */
  value: string
  /** The pills in the text (ARA-096). */
  mentions?: readonly DraftMention[]
  onValueChange: (value: string, mentions: DraftMention[]) => void
  onSubmit: () => void
  /** Accessible name of the text field, e.g. "Research topic" or "Question about this paper". */
  label: string
  placeholder: string
  submitLabel: string
  disabled?: boolean
  submitDisabled?: boolean
  /** While busy, the send button becomes Stop when onStop is given. */
  busy?: boolean
  onStop?: () => void
  stopLabel?: string
  /** Chips shown above the text, such as the paper being asked about. */
  header?: React.ReactNode
  /** Controls on the left of the toolbar (attach, provider). */
  leading?: React.ReactNode
  /** Controls before the send button (model switcher). */
  trailing?: React.ReactNode
  /** One line under the composer: why it is disabled, or a quiet reminder. */
  footnote?: React.ReactNode
  /** Typing @ at the start of a word calls this, to open the paper picker; a picked paper becomes a pill. */
  onMention?: (mention: Mention) => void
  maxLength?: number
  autoFocus?: boolean
  size?: 'default' | 'large'
  className?: string
}

/**
 * The one input surface of the app: Enter sends, Shift+Enter adds a line. A TipTap editor (ARA-096), so a paper
 * mentioned with @ is an atomic pill rather than text.
 */
export function Composer({ value, mentions = noMentions, onValueChange, onSubmit, label, placeholder, submitLabel, disabled = false, submitDisabled, busy, onStop, stopLabel = 'Stop generation', header, leading, trailing, footnote, onMention, maxLength = 8000, autoFocus, size = 'default', className }: ComposerProps) {
  const canSubmit = !disabled && !submitDisabled && !busy && value.trim().length > 0
  const stopping = busy && onStop
  const mentionable = !!onMention
  // The editor is created once; its settings change through `configure`, and it reports back through events.
  const [extensions] = useState(() => composerExtensions({ label, placeholder, disabled, size, limit: maxLength, mentionable }))
  const [content] = useState(() => toContent({ text: value, mentions: [...mentions] }))
  const editor = useEditor({ extensions, content, editable: !disabled })
  // Drafts the editor reported that the owner may still hand back; an older one can arrive after a newer keystroke.
  const reported = useRef([draftKey({ text: value, mentions: [...mentions] })])
  const focusOnMount = useRef(autoFocus)
  const submit = useEffectEvent(() => { if (canSubmit) onSubmit() })
  const mention = useEffectEvent((handle: Mention) => onMention?.(handle))
  const change = useEffectEvent((text: string, next: DraftMention[]) => onValueChange(text, next))
  useEffect(() => {
    const updated = ({ editor: current }: { editor: Editor }) => {
      const draft = toDraft(current.state.doc)
      reported.current.push(draftKey(draft))
      change(draft.text, draft.mentions)
    }
    const submitted = () => submit()
    const mentioned = (handle: Mention) => mention(handle)
    editor.on('update', updated).on('composerSubmit', submitted).on('composerMention', mentioned)
    return () => { editor.off('update', updated).off('composerSubmit', submitted).off('composerMention', mentioned) }
  }, [editor])
  useEffect(() => {
    configure(editor, { label, placeholder, disabled, size, limit: maxLength, mentionable })
    if (editor.isEditable !== !disabled) editor.setEditable(!disabled, false)
  }, [editor, label, placeholder, disabled, size, maxLength, mentionable])
  // Focus on mount as a textarea's autoFocus does; TipTap's own autofocus waits for an animation frame.
  useEffect(() => {
    if (focusOnMount.current) editor.view.focus()
  }, [editor])
  // A draft set by the owner (cleared after sending, a queued question restored) replaces the editor's content.
  useEffect(() => {
    const draft = { text: value, mentions: [...mentions] }
    const echo = reported.current.lastIndexOf(draftKey(draft))
    if (echo >= 0) {
      reported.current = reported.current.slice(echo)
      return
    }
    reported.current = [draftKey(draft)]
    setDraft(editor, draft)
  }, [editor, value, mentions])
  return (
    <div className={cn('w-full', className)}>
      <form
        onSubmit={(event) => { event.preventDefault(); if (canSubmit) onSubmit() }}
        onClick={(event) => { if (event.target === event.currentTarget) editor.commands.focus() }}
        className={cn(
          'relative flex w-full cursor-text flex-col rounded-3xl border bg-background shadow-[0_1px_2px_rgb(0_0_0/0.04),0_4px_16px_-4px_rgb(0_0_0/0.08)] transition-[border-color,box-shadow] focus-within:border-ring/60 focus-within:shadow-[0_1px_2px_rgb(0_0_0/0.05),0_8px_24px_-6px_rgb(0_0_0/0.12)] dark:bg-card dark:shadow-none',
          disabled && 'cursor-not-allowed opacity-70',
        )}
      >
        {header && <div className="flex flex-wrap gap-1.5 px-3 pt-3">{header}</div>}
        <EditorContent editor={editor} />
        <div className="flex items-center gap-1 px-2 pb-2">
          <div className="flex min-w-0 flex-1 items-center gap-0.5">{leading}</div>
          {trailing}
          {stopping ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button type="button" size="icon-sm" className="ml-1 rounded-full" aria-label={stopLabel} onClick={onStop}><Square className="size-3 fill-current" aria-hidden="true" /></Button>
              </TooltipTrigger>
              <TooltipContent>{stopLabel}</TooltipContent>
            </Tooltip>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button type="submit" size="icon-sm" className="ml-1 rounded-full" aria-label={submitLabel} disabled={!canSubmit}><ArrowUp aria-hidden="true" /></Button>
              </TooltipTrigger>
              <TooltipContent>{submitLabel}</TooltipContent>
            </Tooltip>
          )}
        </div>
      </form>
      {footnote && <div className="px-4 pt-2 text-center text-xs text-muted-foreground">{footnote}</div>}
    </div>
  )
}
