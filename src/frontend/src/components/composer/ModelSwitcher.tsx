import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, ChevronDown, Settings2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup,
  DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { unavailableReason, useSaveDefaults, type Purpose } from '@/hooks/queries/models'
import { cn } from '@/lib/utils'
import { effortLabel } from './effort'
import { useGenerationSettings } from './generation-settings-context'


/** Compact model and reasoning-effort picker. The choice applies to the next request; "Set as default" saves it. */
export function ModelSwitcher({ purpose, disabled, align = 'start', className }: { purpose?: Purpose; disabled?: boolean; align?: 'start' | 'end'; className?: string }) {
  const { settings, setSettings, models, selectedModel, savedDefaults, loading } = useGenerationSettings()
  const save = useSaveDefaults()
  const [open, setOpen] = useState(false)
  const isDefault = savedDefaults?.model === settings.model && savedDefaults.reasoning_effort === settings.reasoning_effort
  const name = selectedModel?.display_name ?? (loading ? 'Loading models' : 'Choose a model')
  const effort = selectedModel ? effortLabel(settings.reasoning_effort) : null
  return (
    <DropdownMenu open={open} onOpenChange={(next) => { setOpen(next); if (next) save.reset() }}>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="sm" disabled={disabled || loading || !models.length} aria-label={`Model: ${name}${effort ? `, ${effort} reasoning` : ''}`} className={cn('gap-1 rounded-full px-2.5 text-muted-foreground hover:text-foreground', className)}>
          <span className="font-medium text-foreground">{name}</span>
          {effort && <span>{effort}</span>}
          <ChevronDown className="size-3.5 opacity-60" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align={align} className="w-72">
        <DropdownMenuLabel>Model</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={settings.model} onValueChange={(model) => { const option = models.find((item) => item.key === model); if (option && !unavailableReason(option, purpose)) setSettings({ model, reasoning_effort: settings.reasoning_effort }) }}>
          {models.map((model) => {
            const reason = unavailableReason(model, purpose)
            const item = (
              <DropdownMenuRadioItem key={model.key} value={model.key} aria-disabled={!!reason} onSelect={(event) => { if (reason) event.preventDefault() }} className={cn('items-start py-2', reason && 'text-muted-foreground')}>
                <div className="grid gap-0.5">
                  <span>{model.display_name}</span>
                  <span className="text-xs text-muted-foreground">{reason ?? model.model_id}</span>
                </div>
              </DropdownMenuRadioItem>
            )
            return reason ? <Tooltip key={model.key}><TooltipTrigger asChild>{item}</TooltipTrigger><TooltipContent>{reason}</TooltipContent></Tooltip> : item
          })}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuSub>
          <DropdownMenuSubTrigger disabled={!selectedModel?.reasoning_efforts.length}>
            Reasoning effort
            <span className="ml-auto pl-4 text-xs text-muted-foreground">{effort}</span>
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent className="w-44">
            <DropdownMenuRadioGroup value={settings.reasoning_effort} onValueChange={(reasoning_effort) => setSettings({ model: settings.model, reasoning_effort })}>
              {(selectedModel?.reasoning_efforts ?? []).map((value) => <DropdownMenuRadioItem key={value} value={value}>{effortLabel(value)}</DropdownMenuRadioItem>)}
            </DropdownMenuRadioGroup>
          </DropdownMenuSubContent>
        </DropdownMenuSub>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem
            disabled={isDefault || !selectedModel || !!unavailableReason(selectedModel, purpose) || save.isPending}
            onSelect={(event) => {
              // Stay open while saving so a failure can be explained here; errors are never toasts.
              event.preventDefault()
              save.mutate(settings, { onSuccess: () => { setOpen(false); toast.success('Saved as default model') } })
            }}
          >
            <Check aria-hidden="true" className={cn(!isDefault && 'opacity-0')} />
            {isDefault ? 'Default model' : 'Set as default'}
          </DropdownMenuItem>
          <DropdownMenuItem asChild><Link to="/settings#local-models"><Settings2 aria-hidden="true" />Model settings</Link></DropdownMenuItem>
        </DropdownMenuGroup>
        {save.error && <p role="alert" className="px-2 pt-1 pb-1.5 text-xs text-destructive">{save.error.message}</p>}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
