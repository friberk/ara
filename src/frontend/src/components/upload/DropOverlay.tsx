import { Upload } from 'lucide-react'

/** Shown while files are dragged over the page; the page itself announces what happens after the drop. */
export function DropOverlay({ show, label }: { show: boolean; label: string }) {
  if (!show) return null
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-3 z-50 grid place-items-center rounded-2xl border-2 border-dashed border-foreground/25 bg-background/90">
      <div className="grid justify-items-center gap-2 px-6 text-center">
        <span className="flex size-12 items-center justify-center rounded-full bg-muted"><Upload className="size-5" /></span>
        <p className="text-base font-medium text-balance">{label}</p>
        <p className="text-sm text-muted-foreground">Text-based PDFs, up to 25 MB each</p>
      </div>
    </div>
  )
}
