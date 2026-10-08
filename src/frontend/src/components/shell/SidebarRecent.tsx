import { useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { MessageSquare, MoreHorizontal, Pencil, Search, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { SidebarGroup, SidebarGroupLabel, SidebarMenu, SidebarMenuAction, SidebarMenuButton, SidebarMenuItem, SidebarMenuSkeleton, useSidebar } from '@/components/ui/sidebar'
import { useChats } from '@/hooks/queries/chats'
import { useDeleteSearch, useSearchHistory } from '@/hooks/queries/search'
import { DeleteChatDialog, RenameChatDialog } from './chat-dialogs'
import { mergeRecent, type RecentItem } from './recent-items'

function RecentRow({ item, active, onNavigate }: { item: RecentItem; active: boolean; onNavigate: () => void }) {
  const [dialog, setDialog] = useState<'rename' | 'delete' | null>(null)
  const removeSearch = useDeleteSearch()
  const Icon = item.kind === 'chat' ? MessageSquare : Search
  return (
    <SidebarMenuItem>
      <SidebarMenuButton asChild isActive={active} tooltip={item.title}>
        <Link to={item.href} onClick={onNavigate} title={item.detail ? `${item.title}\n${item.detail}` : item.title}>
          <Icon aria-hidden="true" className="text-sidebar-foreground/60" />
          <span>{item.title}</span>
        </Link>
      </SidebarMenuButton>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <SidebarMenuAction showOnHover aria-label={`Options for ${item.title}`}><MoreHorizontal /></SidebarMenuAction>
        </DropdownMenuTrigger>
        <DropdownMenuContent side="right" align="start" className="w-48">
          {item.kind === 'chat' ? (
            <>
              <DropdownMenuItem onSelect={() => setDialog('rename')}><Pencil aria-hidden="true" />Rename</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onSelect={() => setDialog('delete')}><Trash2 aria-hidden="true" />Delete</DropdownMenuItem>
            </>
          ) : (
            <DropdownMenuItem variant="destructive" onSelect={() => removeSearch.mutate(item.id, { onSuccess: () => toast.success('Search removed from history') })}><Trash2 aria-hidden="true" />Remove from history</DropdownMenuItem>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {item.kind === 'chat' && dialog === 'rename' && <RenameChatDialog chat={item.chat} onClose={() => setDialog(null)} />}
      {item.kind === 'chat' && dialog === 'delete' && <DeleteChatDialog chat={item.chat} onClose={() => setDialog(null)} />}
    </SidebarMenuItem>
  )
}

/** Recent conversations and searches, like a chat app's history. */
export function SidebarRecent() {
  const chats = useChats({ limit: 20 })
  const searches = useSearchHistory(20)
  const location = useLocation()
  const { isMobile, setOpenMobile } = useSidebar()
  const items = mergeRecent(chats.data?.items ?? [], searches.data?.items ?? [])
  const current = `${location.pathname}${location.search}`
  const loading = chats.isPending || searches.isPending
  const failed = chats.isError && searches.isError
  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      <SidebarGroupLabel>Recent</SidebarGroupLabel>
      <SidebarMenu>
        {loading && Array.from({ length: 4 }, (_, index) => <SidebarMenuItem key={index}><SidebarMenuSkeleton /></SidebarMenuItem>)}
        {failed && (
          <li className="px-2 py-1 text-xs text-sidebar-foreground/60">
            History could not load. <button type="button" className="underline" onClick={() => { void chats.refetch(); void searches.refetch() }}>Try again</button>
          </li>
        )}
        {!loading && !failed && !items.length && <li className="px-2 py-1 text-xs text-sidebar-foreground/60">Searches and conversations appear here.</li>}
        {items.map((item) => (
          <RecentRow key={`${item.kind}:${item.id}`} item={item} active={item.kind === 'chat' ? location.pathname.endsWith(`/chats/${item.id}`) : current === item.href} onNavigate={() => { if (isMobile) setOpenMobile(false) }} />
        ))}
      </SidebarMenu>
    </SidebarGroup>
  )
}
