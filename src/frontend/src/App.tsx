import { lazy } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Toaster } from '@/components/ui/sonner'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import { AppShell } from '@/components/shell/AppShell'
import HomePage from '@/features/research/HomePage'

const SearchPage = lazy(() => import('@/features/research/SearchPage'))
const LibraryPage = lazy(() => import('@/features/library/LibraryPage'))
const SettingsPage = lazy(() => import('@/features/settings/SettingsPage'))
const PaperWorkspacePage = lazy(() => import('@/features/workspace/PaperWorkspacePage'))

export default function App() {
  return (
    <ThemeProvider>
      <TooltipProvider delayDuration={300}>
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<HomePage />} />
            <Route path="search" element={<SearchPage />} />
            <Route path="library" element={<LibraryPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="papers/:paperId" element={<PaperWorkspacePage />} />
            <Route path="papers/:paperId/chats/:chatId" element={<PaperWorkspacePage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
        <Toaster position="bottom-right" />
      </TooltipProvider>
    </ThemeProvider>
  )
}
