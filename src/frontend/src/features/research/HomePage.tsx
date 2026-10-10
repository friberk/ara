import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FileText, FileUp, History, Plus, X } from 'lucide-react'
import { toast } from 'sonner'
import type { Paper, Provider } from '@/api/types'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Composer } from '@/components/composer/Composer'
import { ModelSwitcher } from '@/components/composer/ModelSwitcher'
import { PaperChips, PaperPicker } from '@/components/composer/PaperPicker'
import { ProviderSwitcher } from '@/components/composer/ProviderSwitcher'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { chatHref, searchHref } from '@/components/shell/recent-items'
import { Progress } from '@/components/ui/progress'
import { UploadFailure } from '@/components/upload/UploadDropzone'
import { DropOverlay } from '@/components/upload/DropOverlay'
import { usePageDrop } from '@/components/upload/use-page-drop'
import { useUploads } from '@/components/upload/use-upload'
import { useCreateChat } from '@/hooks/queries/chats'
import { useRecordSearch, useSearchHistory } from '@/hooks/queries/search'
import { queueQuestion } from '@/lib/pending-questions'

const exampleTopics = ['Retrieval-augmented generation', 'Graph neural networks for molecules', 'Evaluating large language models']
const SUGGESTION_COUNT = 3
const chip = 'max-w-full rounded-full font-normal text-muted-foreground'

/** The first viewport: one composer that searches the literature, or asks a paper from the library. */
export default function HomePage() {
  const navigate = useNavigate()
  const [text, setText] = useState('')
  const [provider, setProvider] = useState<Provider>('openalex')
  // Library papers to ask about, in the order chosen; the first one's page is the chat's address (ARA-088).
  const [papers, setPapers] = useState<Paper[]>([])
  const picker = useRef<HTMLInputElement>(null)
  const [picking, setPicking] = useState(false)
  // Opened by typing @: the cursor returns to the composer afterwards.
  const [refocus, setRefocus] = useState<(() => void) | undefined>(undefined)
  // A PDF chosen or dropped here uploads at once and opens its paper, where the same steps continue.
  const uploads = useUploads({
    onAccepted: (accepted) => {
      if (accepted.duplicate) toast('This PDF is already in your library, so its paper opened.')
      navigate(`/papers/${accepted.paper_id}`, { state: { upload: { jobId: accepted.job_id } } })
    },
  })
  const upload = uploads.items.at(-1)
  const startUpload = (files: File[]) => {
    if (!files[0]) return
    for (const item of uploads.items) uploads.remove(item.id)
    uploads.add([files[0]])
  }
  const dragging = usePageDrop(startUpload)
  const record = useRecordSearch()
  // Same query as the sidebar's recent list, so both share one request. Missing history just leaves the examples.
  const history = useSearchHistory(20)
  const recent = (history.data?.items ?? []).slice(0, SUGGESTION_COUNT)
  const examples = exampleTopics.filter((topic) => !recent.some((item) => item.query.toLowerCase() === topic.toLowerCase())).slice(0, Math.max(0, SUGGESTION_COUNT - recent.length))
  const generation = useGenerationSettings()
  const createChat = useCreateChat()
  const asking = papers.length > 0
  const several = papers.length > 1
  const toggle = (choice: Paper) => setPapers((current) => current.some((item) => item.id === choice.id) ? current.filter((item) => item.id !== choice.id) : [...current, choice])

  function search(q: string) {
    const params = { q: q.trim(), provider }
    record.mutate(params)
    navigate(`/search?${new URLSearchParams(params)}`)
  }
  function ask() {
    if (!asking) return
    const content = text.trim()
    createChat.mutate({ paperIds: papers.map((item) => item.id) }, {
      onSuccess: (chat) => {
        queueQuestion(chat.id, { content, settings: generation.settings })
        navigate(chatHref(chat))
      },
    })
  }

  return (
    <div className="flex flex-1 flex-col items-center justify-center px-4 pb-[12vh]">
      <div className="flex w-full max-w-3xl flex-col items-center gap-7">
        <h1 className="text-center text-[28px] font-semibold tracking-tight text-balance">{asking ? 'What would you like to know?' : 'What are you researching?'}</h1>
        <Composer
          size="large"
          autoFocus
          value={text}
          onValueChange={setText}
          onSubmit={() => (asking ? ask() : search(text))}
          label={several ? 'Question about these papers' : asking ? 'Question about this paper' : 'Research topic'}
          placeholder={several ? 'Ask a question about these papers' : asking ? 'Ask a question about this paper' : 'Search papers by topic, title or research question'}
          submitLabel={asking ? 'Ask question' : 'Search papers'}
          maxLength={asking ? 8000 : 300}
          submitDisabled={asking ? createChat.isPending || !generation.usableFor('chat') : false}
          header={asking && <PaperChips papers={papers} onRemove={(item) => setPapers((current) => current.filter((chosen) => chosen.id !== item.id))} />}
          onMention={(back) => { setRefocus(() => back); setPicking(true) }}
          leading={
            <>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button type="button" variant="ghost" size="icon-sm" className="rounded-full text-muted-foreground hover:text-foreground" aria-label="Add a paper"><Plus aria-hidden="true" /></Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-56">
                  <DropdownMenuItem onSelect={() => picker.current?.click()}><FileUp aria-hidden="true" />Upload a PDF</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <PaperPicker selected={papers.map((item) => item.id)} onSelect={toggle} open={picking} onOpenChange={setPicking} refocus={refocus && (() => { refocus(); setRefocus(undefined) })} />
              {!asking && <ProviderSwitcher value={provider} onChange={setProvider} />}
            </>
          }
          trailing={asking ? <ModelSwitcher purpose="chat" align="end" /> : undefined}
          footnote={several ? 'Answers come from these papers’ PDFs and cite their pages. Check important claims against the source.' : asking ? 'Answers come from this paper’s PDF and cite their pages. Check important claims against the source.' : undefined}
        />
        <ErrorNotice error={createChat.error} className="w-full" />
        <input ref={picker} type="file" accept="application/pdf,.pdf" aria-label="PDF file" tabIndex={-1} className="sr-only" onChange={(event) => { startUpload(Array.from(event.target.files ?? [])); event.target.value = '' }} />
        {upload?.state === 'uploading' && (
          <div className="grid w-full gap-2 rounded-xl border bg-card px-4 py-3">
            <div className="flex items-center gap-3">
              <FileText className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
              <p className="min-w-0 flex-1 truncate text-sm font-medium">{upload.file.name}</p>
              <span className="tabular text-xs text-muted-foreground">Uploading {Math.round(upload.progress * 100)}%</span>
              <Button type="button" size="icon-sm" variant="ghost" aria-label="Cancel upload" onClick={() => uploads.remove(upload.id)}><X /></Button>
            </div>
            <Progress value={Math.round(upload.progress * 100)} aria-label="Upload progress" />
          </div>
        )}
        {upload?.state === 'failed' && <UploadFailure item={upload} onRetry={() => uploads.retry(upload)} className="w-full" />}
        {!asking && (
          <ul aria-label="Suggestions" className="flex max-w-full flex-wrap justify-center gap-2">
            {recent.map((item) => (
              <li key={item.id} className="max-w-full">
                <Button asChild variant="outline" size="sm" className={chip}>
                  <Link to={searchHref(item)}><History aria-hidden="true" /><span className="sr-only">Recent search:</span> <span className="truncate">{item.query}</span></Link>
                </Button>
              </li>
            ))}
            {examples.map((topic) => (
              <li key={topic} className="max-w-full">
                <Button type="button" variant="outline" size="sm" className={chip} onClick={() => search(topic)}><span className="sr-only">Example topic:</span> <span className="truncate">{topic}</span></Button>
              </li>
            ))}
            <li><Button type="button" variant="outline" size="sm" className={chip} onClick={() => picker.current?.click()}><FileUp aria-hidden="true" />Upload a PDF</Button></li>
          </ul>
        )}
      </div>
      <DropOverlay show={dragging} label="Drop a PDF to open it as a paper" />
    </div>
  )
}
