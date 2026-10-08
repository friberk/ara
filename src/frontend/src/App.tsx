import { lazy, Suspense } from 'react'
import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { BookOpen, Search, Library, ListChecks, Settings } from 'lucide-react'

import SearchPage from './pages/SearchPage'
import LibraryPage from './pages/LibraryPage'
import { Loading } from './components/Feedback'
import JobsPage from './pages/JobsPage'
import SettingsPage from './pages/SettingsPage'

const PaperPage = lazy(() => import('./pages/PaperPage'))

export default function App() {
  const links = [{ to: '/search', label: 'Search', icon: Search }, { to: '/library', label: 'Library', icon: Library }, { to: '/jobs', label: 'Jobs', icon: ListChecks }, { to: '/settings', label: 'Settings', icon: Settings }]
  return <div className="app-shell">
    <a href="#main" className="skip-link">Skip to content</a>
    <aside className="sidebar"><NavLink to="/search" className="brand"><BookOpen aria-hidden="true"/><span>Research<br/><strong>Assistant</strong></span></NavLink>
      <nav aria-label="Workspace">{links.map(({ to, label, icon: Icon }) => <NavLink key={to} to={to} className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}><Icon size={19} aria-hidden="true"/>{label}</NavLink>)}</nav>
      <p className="sidebar-note">A place for papers,<br/>questions, and understanding.</p>
    </aside>
    <main id="main" className="workspace"><Routes><Route path="/search" element={<SearchPage/>}/><Route path="/library" element={<LibraryPage/>}/><Route path="/papers/:id" element={<Suspense fallback={<Loading>Loading paper workspace…</Loading>}><PaperPage/></Suspense>}/><Route path="/jobs" element={<JobsPage/>}/><Route path="/settings" element={<SettingsPage/>}/><Route path="*" element={<Navigate to="/search" replace/>}/></Routes></main>
  </div>
}
