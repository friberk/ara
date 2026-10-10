import { lazy, Suspense, useState } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import { AppShell } from '@/components/shell/AppShell'
import HomePage from '@/features/research/HomePage'
import { useSettingsDialog } from '@/features/settings/settings-url'

const SearchPage = lazy(() => import('@/features/research/SearchPage'))
const LibraryPage = lazy(() => import('@/features/library/LibraryPage'))
const SettingsDialog = lazy(() => import('@/features/settings/SettingsDialog'))
const PaperWorkspacePage = lazy(() => import('@/features/workspace/PaperWorkspacePage'))

/** Settings is a dialog now (ARA-109): old /settings links open it over home, and #local-models opens Open models. */
function LegacySettings() {
  const { hash } = useLocation()
  const category = hash === '#local-models' ? 'open-models' : ''
  return <Navigate replace to={{ pathname: '/', search: `?settings=${category}`, hash }} />
}

/** Loads the Settings dialog the first time the URL asks for it, and keeps it mounted so closing can animate. */
function SettingsHost() {
  const { isOpen } = useSettingsDialog()
  const [loaded, setLoaded] = useState(isOpen)
  if (isOpen && !loaded) setLoaded(true)
  return loaded ? <Suspense fallback={null}><SettingsDialog /></Suspense> : null
}

export default function App() {
  return (
    <ThemeProvider>
      <TooltipProvider delayDuration={300}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<HomePage />} />
            <Route path="search" element={<SearchPage />} />
            <Route path="library" element={<LibraryPage />} />
            <Route path="settings" element={<LegacySettings />} />
            <Route path="papers/:paperId" element={<PaperWorkspacePage />} />
            <Route path="papers/:paperId/chats/:chatId" element={<PaperWorkspacePage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
        <SettingsHost />
        <Toaster position="bottom-right" />
      </TooltipProvider>
    </ThemeProvider>
  )
}
