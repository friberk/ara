import { useNavigate } from 'react-router-dom'
import { Cpu, Library, MessageSquare, Moon, Settings, SquarePen, Sun, Upload } from 'lucide-react'
import { useTheme } from '@/components/theme/theme-context'
import { Command, CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList, CommandSeparator } from '@/components/ui/command'
import { PdfStateIcon } from '@/components/paper/PdfStateIcon'
import { useChats } from '@/hooks/queries/chats'
import { usePapers } from '@/hooks/queries/papers'
import { chatPapersLabel } from '@/lib/paper-names'
import { type SettingsCategory, useSettingsDialog } from '@/features/settings/settings-url'
import { chatDisplayTitle, chatHref } from './recent-items'

/** Jump to a paper or conversation, or run a common action. Loaded on first open (⌘K / Ctrl+K). */
export default function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate()
  const { resolvedTheme, setTheme } = useTheme()
  const papers = usePapers('', { pageSize: 50, enabled: open })
  const chats = useChats({ limit: 30 })
  const settings = useSettingsDialog()
  const go = (to: string) => { onOpenChange(false); navigate(to) }
  const openSettings = (category: SettingsCategory | '') => { onOpenChange(false); settings.open(category) }
  const paperItems = papers.data?.pages.flatMap((page) => page.items) ?? []
  return (
    <CommandDialog open={open} onOpenChange={onOpenChange} title="Find papers and chats" description="Search your library and conversations, or run an action.">
      <Command>
        <CommandInput placeholder="Search papers, conversations and actions" />
        <CommandList>
          <CommandEmpty>No matches.</CommandEmpty>
          <CommandGroup heading="Actions">
            <CommandItem onSelect={() => go('/')}><SquarePen aria-hidden="true" />New research</CommandItem>
            <CommandItem onSelect={() => go('/library#upload')}><Upload aria-hidden="true" />Upload a PDF</CommandItem>
            <CommandItem onSelect={() => go('/library')}><Library aria-hidden="true" />Open library</CommandItem>
            <CommandItem onSelect={() => openSettings('')}><Settings aria-hidden="true" />Settings</CommandItem>
            <CommandItem onSelect={() => openSettings('models')}><Cpu aria-hidden="true" />Model settings</CommandItem>
            <CommandItem onSelect={() => { setTheme(resolvedTheme === 'dark' ? 'light' : 'dark'); onOpenChange(false) }}>
              {resolvedTheme === 'dark' ? <Sun aria-hidden="true" /> : <Moon aria-hidden="true" />}
              {resolvedTheme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
            </CommandItem>
          </CommandGroup>
          {paperItems.length > 0 && <CommandSeparator />}
          {paperItems.length > 0 && (
            <CommandGroup heading="Papers">
              {paperItems.map((paper) => (
                <CommandItem key={paper.id} value={`paper ${paper.title ?? ''} ${paper.authors.join(' ')} ${paper.id}`} onSelect={() => go(`/papers/${paper.id}`)}>
                  <PdfStateIcon state={paper.document_status} focusable={false} />
                  <span className="truncate">{paper.title ?? 'Untitled paper'}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          )}
          {!!chats.data?.items.length && <CommandSeparator />}
          {!!chats.data?.items.length && (
            <CommandGroup heading="Conversations">
              {chats.data.items.map((chat) => (
                <CommandItem key={chat.id} value={`chat ${chatDisplayTitle(chat)} ${chat.papers.map((paper) => paper.title ?? '').join(' ')} ${chat.id}`} onSelect={() => go(chatHref(chat))}>
                  <MessageSquare aria-hidden="true" />
                  <span className="truncate">{chatDisplayTitle(chat)}</span>
                  {chatPapersLabel(chat.papers) && <span className="ml-auto max-w-[40%] shrink-0 truncate text-xs text-muted-foreground">{chatPapersLabel(chat.papers)}</span>}
                </CommandItem>
              ))}
            </CommandGroup>
          )}
        </CommandList>
      </Command>
    </CommandDialog>
  )
}
