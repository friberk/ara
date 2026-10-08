import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { FileUp, History, Plus } from 'lucide-react'
import type { Paper, Provider } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Composer } from '@/components/composer/Composer'
import { ModelSwitcher } from '@/components/composer/ModelSwitcher'
import { PaperContextChip, PaperPicker } from '@/components/composer/PaperPicker'
import { ProviderSwitcher } from '@/components/composer/ProviderSwitcher'
import { useGenerationSettings } from '@/components/composer/generation-settings-context'
import { ErrorNotice } from '@/components/feedback/ErrorNotice'
import { searchHref } from '@/components/shell/recent-items'
import { UploadDropzone } from '@/components/upload/UploadDropzone'
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
  const [paper, setPaper] = useState<Paper | null>(null)
  const [uploadOpen, setUploadOpen] = useState(false)
  const record = useRecordSearch()
  // Same query as the sidebar's recent list, so both share one request. Missing history just leaves the examples.
  const history = useSearchHistory(20)
  const recent = (history.data?.items ?? []).slice(0, SUGGESTION_COUNT)
  const examples = exampleTopics.filter((topic) => !recent.some((item) => item.query.toLowerCase() === topic.toLowerCase())).slice(0, Math.max(0, SUGGESTION_COUNT - recent.length))
  const generation = useGenerationSettings()
  const createChat = useCreateChat(paper?.id ?? '')
  const asking = !!paper

  function search(q: string) {
    const params = { q: q.trim(), provider }
    record.mutate(params)
    navigate(`/search?${new URLSearchParams(params)}`)
  }
  function ask() {
    if (!paper) return
    const content = text.trim()
    createChat.mutate(undefined, {
      onSuccess: (chat) => {
        queueQuestion(chat.id, { content, settings: generation.settings })
        navigate(`/papers/${paper.id}/chats/${chat.id}`)
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
          label={asking ? 'Question about this paper' : 'Research topic'}
          placeholder={asking ? 'Ask a question about this paper' : 'Search papers by topic, title or research question'}
          submitLabel={asking ? 'Ask question' : 'Search papers'}
          maxLength={asking ? 8000 : 300}
          submitDisabled={asking ? createChat.isPending || !generation.usableFor('chat') : false}
          header={paper && <PaperContextChip paper={paper} onRemove={() => setPaper(null)} />}
          leading={
            <>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button type="button" variant="ghost" size="icon-sm" className="rounded-full text-muted-foreground hover:text-foreground" aria-label="Add a paper"><Plus aria-hidden="true" /></Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="w-56">
                  <DropdownMenuItem onSelect={() => setUploadOpen(true)}><FileUp aria-hidden="true" />Upload a PDF</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
              <PaperPicker onSelect={setPaper} />
              {!asking && <ProviderSwitcher value={provider} onChange={setProvider} />}
            </>
          }
          trailing={asking ? <ModelSwitcher purpose="chat" align="end" /> : undefined}
          footnote={asking ? 'Answers come from this paper’s PDF and cite their pages. Check important claims against the source.' : undefined}
        />
        <ErrorNotice error={createChat.error} className="w-full" />
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
            <li><Button type="button" variant="outline" size="sm" className={chip} onClick={() => setUploadOpen(true)}><FileUp aria-hidden="true" />Upload a PDF</Button></li>
          </ul>
        )}
      </div>
      <Dialog open={uploadOpen} onOpenChange={setUploadOpen}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Upload a paper</DialogTitle>
            <DialogDescription>We read the title, authors, year and abstract from the PDF, then prepare it for summaries and questions.</DialogDescription>
          </DialogHeader>
          <UploadDropzone onAccepted={(accepted) => { setUploadOpen(false); navigate(`/papers/${accepted.paper_id}`) }} />
        </DialogContent>
      </Dialog>
    </div>
  )
}
