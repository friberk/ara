import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { MessageSquare, MoreHorizontal, Pencil, Search, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import type { ChatSummary } from '@/api/types'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { SidebarGroup, SidebarGroupLabel, SidebarMenu, SidebarMenuAction, SidebarMenuButton, SidebarMenuItem, SidebarMenuSkeleton, useSidebar } from '@/components/ui/sidebar'
import { useChats, useDeleteChat, useRenameChat } from '@/hooks/queries/chats'
import { useDeleteSearch, useSearchHistory } from '@/hooks/queries/search'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { mergeRecent, type RecentItem } from './recent-items'

function RenameChatDialog({ chat, onClose }: { chat: ChatSummary; onClose: () => void }) {
  const [title, setTitle] = useState(chat.title)
  const rename = useRenameChat()
  const trimmed = title.trim()
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); if (trimmed) rename.mutate({ chatId: chat.id, title: trimmed }, { onSuccess: () => { toast.success('Conversation renamed'); onClose() } }) }}>
          <DialogHeader>
            <DialogTitle>Rename conversation</DialogTitle>
            <DialogDescription>{chat.paper_title ?? 'Paper conversation'}</DialogDescription>
          </DialogHeader>
          <div className="grid gap-2">
            <Label htmlFor="rename-chat">Conversation name</Label>
            <Input id="rename-chat" value={title} maxLength={200} autoFocus onChange={(event) => setTitle(event.target.value)} />
          </div>
          <ErrorNotice error={rename.error} />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
            <Button type="submit" disabled={!trimmed || trimmed === chat.title || rename.isPending}>{rename.isPending ? 'Saving…' : 'Save name'}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function DeleteChatDialog({ chat, onClose }: { chat: ChatSummary; onClose: () => void }) {
  const remove = useDeleteChat()
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <AlertDialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
          <AlertDialogDescription>“{chat.title}” and its answers will be removed. The paper and its summaries stay in your library.</AlertDialogDescription>
        </AlertDialogHeader>
        <ErrorNotice error={remove.error} />
        <AlertDialogFooter>
          <AlertDialogCancel>Cancel</AlertDialogCancel>
          <AlertDialogAction
            variant="destructive"
            disabled={remove.isPending}
            onClick={(event) => {
              event.preventDefault()
              remove.mutate(chat.id, {
                onSuccess: () => {
                  toast.success('Conversation deleted')
                  if (location.pathname.includes(`/chats/${chat.id}`)) navigate(`/papers/${chat.paper_id}`, { replace: true })
                  onClose()
                },
              })
            }}
          >
            {remove.isPending ? 'Deleting…' : 'Delete conversation'}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

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
