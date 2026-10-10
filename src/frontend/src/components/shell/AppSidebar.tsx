import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Library, Search, Settings, SquarePen } from 'lucide-react'
import { Kbd } from '@/components/ui/kbd'
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuButton,
  SidebarMenuItem, SidebarMenuSkeleton, SidebarRail, useSidebar,
} from '@/components/ui/sidebar'
import { AraMark, AraWordmark } from '@/components/brand/AraBrand'
import { PdfStateIcon } from '@/components/paper/PdfStateIcon'
import { usePapers } from '@/hooks/queries/papers'
import { PaperActions } from '@/features/library/PaperActions'
import { useSettingsDialog } from '@/features/settings/settings-url'
import { SidebarRecent } from './SidebarRecent'

function SidebarPapers({ onNavigate }: { onNavigate: () => void }) {
  const papers = usePapers('', { pageSize: 6 })
  const location = useLocation()
  const navigate = useNavigate()
  const items = papers.data?.pages[0]?.items ?? []
  if (papers.isError || (!papers.isPending && !items.length)) return null
  return (
    <SidebarGroup className="group-data-[collapsible=icon]:hidden">
      <SidebarGroupLabel>Papers</SidebarGroupLabel>
      <SidebarMenu>
        {papers.isPending && Array.from({ length: 3 }, (_, index) => <SidebarMenuItem key={index}><SidebarMenuSkeleton /></SidebarMenuItem>)}
        {items.map((paper) => (
          <SidebarMenuItem key={paper.id}>
            <SidebarMenuButton asChild isActive={location.pathname.startsWith(`/papers/${paper.id}`)} tooltip={paper.title ?? 'Untitled paper'}>
              <Link to={`/papers/${paper.id}`} onClick={onNavigate} title={paper.title ?? undefined}>
                <PdfStateIcon state={paper.document_status} focusable={false} />
                <span>{paper.title ?? 'Untitled paper'}</span>
              </Link>
            </SidebarMenuButton>
            <PaperActions
              paper={paper}
              trigger="sidebar"
              onDeleted={() => { if (location.pathname.startsWith(`/papers/${paper.id}`)) navigate('/') }}
            />
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  )
}

export function AppSidebar({ onOpenSearch }: { onOpenSearch: () => void }) {
  const location = useLocation()
  const { isMobile, setOpenMobile, state } = useSidebar()
  const settings = useSettingsDialog()
  const iconOnly = state === 'collapsed' && !isMobile
  const close = () => { if (isMobile) setOpenMobile(false) }
  const links = [
    { to: '/library', label: 'Library', icon: Library },
  ]
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg" asChild tooltip="ara.">
              <Link to="/" onClick={close} aria-label="ara.">
                {iconOnly
                  ? <AraMark decorative className="mx-auto h-6! w-auto! shrink-0" />
                  : <AraWordmark decorative className="h-[26px]! w-auto! shrink-0" />}
              </Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>
      <SidebarContent>
        <SidebarGroup>
          <nav aria-label="Workspace">
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton asChild isActive={location.pathname === '/'} tooltip="New research">
                  <Link to="/" onClick={close}><SquarePen aria-hidden="true" /><span>New research</span></Link>
                </SidebarMenuButton>
              </SidebarMenuItem>
              <SidebarMenuItem>
                <SidebarMenuButton tooltip="Find papers and chats" onClick={() => { close(); onOpenSearch() }}>
                  <Search aria-hidden="true" /><span>Find papers and chats</span>
                  <Kbd className="ml-auto group-data-[collapsible=icon]:hidden">⌘K</Kbd>
                </SidebarMenuButton>
              </SidebarMenuItem>
              {links.map(({ to, label, icon: Icon }) => (
                <SidebarMenuItem key={to}>
                  <SidebarMenuButton asChild isActive={location.pathname.startsWith(to)} tooltip={label}>
                    <Link to={to} onClick={close}><Icon aria-hidden="true" /><span>{label}</span></Link>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </nav>
        </SidebarGroup>
        <SidebarPapers onNavigate={close} />
        <SidebarRecent />
      </SidebarContent>
      <SidebarFooter>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton isActive={settings.isOpen} tooltip="Settings" onClick={() => { settings.open(); close() }}>
              <Settings aria-hidden="true" /><span>Settings</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
