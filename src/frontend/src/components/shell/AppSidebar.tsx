import { Link, useLocation } from 'react-router-dom'
import { Library, Search, Settings, SquarePen } from 'lucide-react'
import { Kbd } from '@/components/ui/kbd'
import {
  Sidebar, SidebarContent, SidebarFooter, SidebarGroup, SidebarGroupLabel, SidebarHeader, SidebarMenu, SidebarMenuButton,
  SidebarMenuItem, SidebarMenuSkeleton, SidebarRail, useSidebar,
} from '@/components/ui/sidebar'
import { AraMark, AraWordmark } from '@/components/brand/AraBrand'
import { PdfStateIcon } from '@/components/paper/PdfStateIcon'
import { ThemeToggle } from '@/components/theme/ThemeToggle'
import { usePapers } from '@/hooks/queries/papers'
import { SidebarRecent } from './SidebarRecent'

function SidebarPapers({ onNavigate }: { onNavigate: () => void }) {
  const papers = usePapers('', { pageSize: 6 })
  const location = useLocation()
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
          </SidebarMenuItem>
        ))}
      </SidebarMenu>
    </SidebarGroup>
  )
}

export function AppSidebar({ onOpenSearch }: { onOpenSearch: () => void }) {
  const location = useLocation()
  const { isMobile, setOpenMobile, state } = useSidebar()
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
            <SidebarMenuButton asChild isActive={location.pathname.startsWith('/settings')} tooltip="Settings">
              <Link to="/settings" onClick={close}><Settings aria-hidden="true" /><span>Settings</span></Link>
            </SidebarMenuButton>
          </SidebarMenuItem>
          <SidebarMenuItem><ThemeToggle /></SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
      <SidebarRail />
    </Sidebar>
  )
}
