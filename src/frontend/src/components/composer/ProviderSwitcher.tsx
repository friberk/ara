import { ChevronDown, Library } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { providerLabels, type Provider } from '@/api/types'
import { cn } from '@/lib/utils'

const descriptions: Record<Provider, string> = { openalex: 'Open catalog of scholarly works', semantic_scholar: 'Research index from Ai2' }

export function ProviderSwitcher({ value, onChange, disabled, className }: { value: Provider; onChange: (provider: Provider) => void; disabled?: boolean; className?: string }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button type="button" variant="ghost" size="sm" disabled={disabled} aria-label={`Academic provider: ${providerLabels[value]}`} className={cn('gap-1.5 rounded-full px-2.5 text-muted-foreground hover:text-foreground', className)}>
          <Library className="size-3.5" aria-hidden="true" />
          <span>{providerLabels[value]}</span>
          <ChevronDown className="size-3.5 opacity-60" aria-hidden="true" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel>Academic provider</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={value} onValueChange={(next) => onChange(next as Provider)}>
          {(Object.keys(providerLabels) as Provider[]).map((provider) => (
            <DropdownMenuRadioItem key={provider} value={provider} className="items-start py-2">
              <div className="grid gap-0.5"><span>{providerLabels[provider]}</span><span className="text-xs text-muted-foreground">{descriptions[provider]}</span></div>
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
