import { Monitor, Moon, Sun } from 'lucide-react'
import { useTheme } from '@/components/theme/theme-context'
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { SidebarMenuButton } from '@/components/ui/sidebar'

const options = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
] as const

export function ThemeToggle() {
  const { theme = 'system', setTheme } = useTheme()
  const current = options.find((option) => option.value === theme) ?? options[2]
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <SidebarMenuButton tooltip="Theme" aria-label={`Theme: ${current.label}`}>
          <current.icon aria-hidden="true" />
          <span>Theme</span>
          <span className="ml-auto text-xs text-sidebar-foreground/60">{current.label}</span>
        </SidebarMenuButton>
      </DropdownMenuTrigger>
      <DropdownMenuContent side="top" align="start" className="w-44">
        <DropdownMenuLabel>Appearance</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={setTheme}>
          {options.map((option) => <DropdownMenuRadioItem key={option.value} value={option.value}><option.icon aria-hidden="true" />{option.label}</DropdownMenuRadioItem>)}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
