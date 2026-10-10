import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import type { ChatSummary } from '@/api/types'
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { useDeleteChat, useRenameChat } from '@/hooks/queries/chats'
import { chatPapersLabel } from '@/lib/paper-names'

// Shared by the sidebar's Recent list and the workspace chat switcher.
export function RenameChatDialog({ chat, onClose }: { chat: Pick<ChatSummary, 'id' | 'paper_id' | 'title' | 'papers'>; onClose: () => void }) {
  const [title, setTitle] = useState(chat.title)
  const rename = useRenameChat()
  const trimmed = title.trim()
  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <DialogContent className="sm:max-w-md">
        <form className="grid gap-4" onSubmit={(event) => { event.preventDefault(); if (trimmed) rename.mutate({ chatId: chat.id, title: trimmed }, { onSuccess: () => { toast.success('Conversation renamed'); onClose() } }) }}>
          <DialogHeader>
            <DialogTitle>Rename conversation</DialogTitle>
            <DialogDescription>{chatPapersLabel(chat.papers) ?? 'Paper conversation'}</DialogDescription>
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

export function DeleteChatDialog({ chat, onClose }: { chat: Pick<ChatSummary, 'id' | 'paper_id' | 'title' | 'papers'>; onClose: () => void }) {
  const remove = useDeleteChat()
  const location = useLocation()
  const navigate = useNavigate()
  return (
    <AlertDialog open onOpenChange={(open) => { if (!open) onClose() }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
          <AlertDialogDescription>“{chat.title}” and its answers will be removed. {chat.papers.length > 1 ? 'The papers and their summaries stay' : 'The paper and its summaries stay'} in your library.</AlertDialogDescription>
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
