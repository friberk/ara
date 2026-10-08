import { useId, useRef } from 'react'
import { ArrowUp, Square } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

export type ComposerProps = {
  value: string
  onValueChange: (value: string) => void
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
  maxLength?: number
  autoFocus?: boolean
  size?: 'default' | 'large'
  className?: string
}

/** The one input surface of the app: Enter sends, Shift+Enter adds a line. */
export function Composer({ value, onValueChange, onSubmit, label, placeholder, submitLabel, disabled, submitDisabled, busy, onStop, stopLabel = 'Stop generation', header, leading, trailing, footnote, maxLength = 8000, autoFocus, size = 'default', className }: ComposerProps) {
  const id = useId()
  const textarea = useRef<HTMLTextAreaElement>(null)
  const canSubmit = !disabled && !submitDisabled && !busy && value.trim().length > 0
  const stopping = busy && onStop
  return (
    <div className={cn('w-full', className)}>
      <form
        onSubmit={(event) => { event.preventDefault(); if (canSubmit) onSubmit() }}
        onClick={(event) => { if (event.target === event.currentTarget) textarea.current?.focus() }}
        className={cn(
          'relative flex w-full cursor-text flex-col rounded-3xl border bg-background shadow-[0_1px_2px_rgb(0_0_0/0.04),0_4px_16px_-4px_rgb(0_0_0/0.08)] transition-[border-color,box-shadow] focus-within:border-ring/60 focus-within:shadow-[0_1px_2px_rgb(0_0_0/0.05),0_8px_24px_-6px_rgb(0_0_0/0.12)] dark:bg-card dark:shadow-none',
          disabled && 'cursor-not-allowed opacity-70',
        )}
      >
        {header && <div className="flex flex-wrap gap-1.5 px-3 pt-3">{header}</div>}
        <label htmlFor={`${id}-input`} className="sr-only">{label}</label>
        <textarea
          ref={textarea}
          id={`${id}-input`}
          rows={1}
          value={value}
          maxLength={maxLength}
          disabled={disabled}
          autoFocus={autoFocus}
          placeholder={placeholder}
          onChange={(event) => onValueChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
              if (canSubmit) onSubmit()
            }
          }}
          className={cn(
            'field-sizing-content max-h-60 w-full resize-none overflow-y-auto bg-transparent px-4 pt-3.5 pb-1 text-[15px] leading-6 outline-none placeholder:text-muted-foreground focus-visible:outline-none disabled:cursor-not-allowed',
            size === 'large' ? 'min-h-16' : 'min-h-11',
          )}
        />
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
