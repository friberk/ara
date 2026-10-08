import { Link } from 'react-router-dom'
import { Check, ChevronDown, Settings2 } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuRadioGroup,
  DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger, DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { unavailableReason, useSaveDefaults, type Purpose } from '@/hooks/queries/models'
import { cn } from '@/lib/utils'
import { useGenerationSettings } from './generation-settings'

const effortLabels: Record<string, string> = { none: 'None', minimal: 'Minimal', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high', max: 'Max' }
export const effortLabel = (effort: string) => effortLabels[effort] ?? effort

/** Compact model and reasoning-effort picker. The choice applies to the next request; "Set as default" saves it. */
export function ModelSwitcher({ purpose, disabled, align = 'start', className }: { purpose?: Purpose; disabled?: boolean; align?: 'start' | 'end'; className?: string }) {
  const { settings, setSettings, models, selectedModel, savedDefaults, loading } = useGenerationSettings()
  const save = useSaveDefaults()
  const isDefault = savedDefaults?.model === settings.model && savedDefaults.reasoning_effort === settings.reasoning_effort
  const name = selectedModel?.display_name ?? (loading ? 'Loading models' : 'Choose a model')
  const effort = selectedModel ? effortLabel(settings.reasoning_effort) : null
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="sm" disabled={disabled || loading || !models.length} aria-label={`Model: ${name}${effort ? `, ${effort} reasoning` : ''}`} className={cn('gap-1 rounded-full px-2.5 text-muted-foreground hover:text-foreground', className)}>
          <span className="font-medium text-foreground">{name}</span>
          {effort && <span>{effort}</span>}
          <ChevronDown className="size-3.5 opacity-60" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align={align} className="w-72">
        <DropdownMenuLabel>Model</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={settings.model} onValueChange={(model) => setSettings({ model, reasoning_effort: settings.reasoning_effort })}>
          {models.map((model) => {
            const reason = unavailableReason(model, purpose)
            return (
              <DropdownMenuRadioItem key={model.key} value={model.key} disabled={!!reason} className="items-start py-2">
                <div className="grid gap-0.5">
                  <span>{model.display_name}</span>
                  <span className="text-xs text-muted-foreground">{reason ?? model.model_id}</span>
                </div>
              </DropdownMenuRadioItem>
            )
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
          <DropdownMenuItem disabled={isDefault || !selectedModel || save.isPending} onSelect={() => save.mutate(settings, { onSuccess: () => toast.success('Saved as default model'), onError: (error) => toast.error(error.message) })}>
            <Check aria-hidden="true" className={cn(!isDefault && 'opacity-0')} />
            {isDefault ? 'Default model' : 'Set as default'}
          </DropdownMenuItem>
          <DropdownMenuItem asChild><Link to="/settings"><Settings2 aria-hidden="true" />Model settings</Link></DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
