import { useId } from 'react'
import { Tabs as TabsPrimitive } from 'radix-ui'
import { ChevronLeft, ChevronRight, Cpu, HardDrive, Library, Settings, X, type LucideIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Dialog, DialogClose, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { useIsMobile } from '@/hooks/use-mobile'
import { useOpenModels } from '@/hooks/queries/features'
import { useModels, useSavedSettings } from '@/hooks/queries/models'
import { cn } from '@/lib/utils'
import { GeneralSettings } from './GeneralSettings'
import { LocalModels } from './LocalModels'
import { ModelSettings } from './ModelSettings'
import { PaperDetailsSettings } from './PaperDetailsSettings'
import { SearchSettings } from './SearchSettings'
import { type SettingsCategory, settingsOpener, useSettingsDialog } from './settings-url'

const categories: { id: SettingsCategory; label: string; icon: LucideIcon }[] = [
  { id: 'general', label: 'General', icon: Settings },
  { id: 'models', label: 'Models', icon: Cpu },
  { id: 'library', label: 'Library and search', icon: Library },
  { id: 'open-models', label: 'Open models', icon: HardDrive },
]

/** Download controls for local models, unchanged from the page they used to sit on (ARA-090: frozen). */
function OpenModelSettings() {
  const models = useModels()
  const saved = useSavedSettings()
  if (!models.data) return <div role="status" className="pt-1"><span className="sr-only">Loading open models…</span><Skeleton className="h-24 w-full rounded-xl" /></div>
  return <div className="pt-1"><LocalModels models={models.data.items} defaultModel={saved.data?.default_model} /></div>
}

/**
 * How answers find their passages, in plain words; each setting below names its step. Checked against the code:
 * keyword search stems English words (rag/retrievers.py), and packing sends the chosen passages in page order within
 * each paper (rag/packing.py), with or without reordering.
 */
function LibraryExplainer() {
  return <p className="max-w-prose pt-1 pb-6 text-sm text-pretty">When you ask about your papers, search looks for the passages that match your question, by its meaning and by its words. Reordering can then sort those passages by how well they answer it. The model that writes the answer reads the top passages in the order they appear in each paper, and cites the page each one comes from.</p>
}

function Panel({ category }: { category: SettingsCategory }) {
  if (category === 'general') return <GeneralSettings />
  if (category === 'models') return <ModelSettings />
  if (category === 'library') return <><LibraryExplainer /><SearchSettings /><PaperDetailsSettings /></>
  return <OpenModelSettings />
}

function CloseButton() {
  return <DialogClose asChild><Button variant="ghost" size="icon-sm" aria-label="Close" className="shrink-0 text-muted-foreground"><X aria-hidden="true" /></Button></DialogClose>
}

/**
 * Settings, grouped by category in a dialog over the current page, as in ChatGPT and Claude. The URL names the open
 * category. On a phone it fills the screen: the category list comes first and each category opens with a way back.
 */
export default function SettingsDialog() {
  const settings = useSettingsDialog()
  const openModels = useOpenModels()
  const isMobile = useIsMobile()
  const panelHeading = useId()
  const shown = categories.filter((category) => category.id !== 'open-models' || openModels)
  // An unknown or hidden category opens the list on a phone and General elsewhere.
  const requested = shown.find((category) => category.id === settings.value)
  const current = requested ?? (isMobile ? null : shown[0])
  const select = (category: SettingsCategory | '') => settings.open(category)
  return (
    <Dialog open={settings.isOpen} onOpenChange={(open) => { if (!open) settings.close() }}>
      <DialogContent
        showCloseButton={false}
        aria-describedby={undefined}
        onCloseAutoFocus={(event) => { const opener = settingsOpener(); if (opener) { event.preventDefault(); opener.focus() } }}
        className={cn(
          'top-0 left-0 flex h-svh w-full max-w-none translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none p-0 ring-0 sm:max-w-none',
          'md:top-1/2 md:left-1/2 md:h-[min(560px,calc(100svh-4rem))] md:max-w-[760px] md:-translate-x-1/2 md:-translate-y-1/2 md:flex-row md:rounded-xl md:ring-1',
        )}
      >
        <TabsPrimitive.Root orientation="vertical" value={current?.id ?? ''} onValueChange={(value) => select(value as SettingsCategory)} className="flex min-h-0 flex-1 flex-col md:flex-row">
          {(!isMobile || !current) && (
            <div className="flex shrink-0 flex-col gap-2 p-2 md:w-52 md:border-r md:bg-sidebar">
              <div className="flex h-11 items-center justify-between gap-2 pr-1 pl-3 md:h-10">
                <DialogTitle className="text-base font-semibold tracking-tight">Settings</DialogTitle>
                {isMobile && <CloseButton />}
              </div>
              <TabsPrimitive.List aria-label="Settings categories" className="grid gap-0.5">
                {shown.map(({ id, label, icon: Icon }) => (
                  <TabsPrimitive.Trigger
                    key={id}
                    value={id}
                    className="flex h-11 w-full items-center gap-2.5 rounded-md px-3 text-left text-sm text-foreground outline-hidden transition-colors hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50 data-[state=active]:bg-accent data-[state=active]:font-medium md:h-8 md:px-2 [&_svg]:size-4 [&_svg]:shrink-0"
                  >
                    <Icon aria-hidden="true" className="text-muted-foreground" />
                    <span className="min-w-0 flex-1 truncate">{label}</span>
                    {isMobile && <ChevronRight aria-hidden="true" className="text-muted-foreground" />}
                  </TabsPrimitive.Trigger>
                ))}
              </TabsPrimitive.List>
            </div>
          )}
          {current && (
            <TabsPrimitive.Content value={current.id} aria-labelledby={panelHeading} className="flex min-h-0 min-w-0 flex-1 flex-col outline-hidden">
              <div className="flex h-14 shrink-0 items-center gap-1 px-2 md:pr-3 md:pl-6">
                {isMobile && (
                  <>
                    <DialogTitle className="sr-only">Settings</DialogTitle>
                    <Button variant="ghost" size="icon-sm" aria-label="All settings" onClick={() => select('')}><ChevronLeft aria-hidden="true" /></Button>
                  </>
                )}
                <h3 id={panelHeading} className="min-w-0 flex-1 truncate text-base font-semibold tracking-tight">{current.label}</h3>
                <CloseButton />
              </div>
              <div className="min-h-0 flex-1 divide-y overflow-y-auto overscroll-contain px-4 pb-6 md:px-6">
                <Panel category={current.id} />
              </div>
            </TabsPrimitive.Content>
          )}
        </TabsPrimitive.Root>
      </DialogContent>
    </Dialog>
  )
}
