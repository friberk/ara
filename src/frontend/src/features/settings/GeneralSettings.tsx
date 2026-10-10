import { useId } from 'react'
import { Monitor, Moon, Sun } from 'lucide-react'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useTheme } from '@/components/theme/theme-context'
import { SettingsSection } from './parts'
import { segmentedGroup, segmentedItem } from './segmented'

const themes = [
  { value: 'system', label: 'System', icon: Monitor },
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
] as const

/** The theme applies at once and is kept in this browser. */
export function GeneralSettings() {
  const { theme, setTheme } = useTheme()
  const id = useId()
  return (
    <SettingsSection
      headingId={id}
      title="Theme"
      description={<p>System follows your device’s light or dark setting.</p>}
      control={(
        <ToggleGroup type="single" role="radiogroup" size="sm" spacing={0.5} aria-labelledby={id} value={theme} onValueChange={(value) => { if (value) setTheme(value) }} className={segmentedGroup}>
          {themes.map(({ value, label, icon: Icon }) => <ToggleGroupItem key={value} value={value} className={segmentedItem}><Icon aria-hidden="true" />{label}</ToggleGroupItem>)}
        </ToggleGroup>
      )}
    />
  )
}
