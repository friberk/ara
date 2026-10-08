import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api, checkedResponse, json } from '../api/client'
import { readEvents } from '../api/sse'
import type { Chat, ChatInput, Collection, GenerationSettings, Message, Paper } from '../api/types'
import { Button } from './ui/button'
import { Citations } from './Citations'
import { GeneratedContent } from './GeneratedContent'
import { Empty, ErrorNotice, Loading } from './Feedback'
function ResponseMetadata({ message }: { message: Message }) {
  if (message.role !== 'assistant') return null
  const model = message.model ?? 'Model not recorded'
  const effort = message.reasoning_effort ? `${message.reasoning_effort} reasoning` : 'Reasoning effort not recorded'
  return <div className="generation-meta">{`${model} · ${effort}`}</div>
}
function Conversation({ chat, settings, allowed }: { chat: Chat; settings: GenerationSettings; allowed: boolean }) {
  const client = useQueryClient(); const [question, setQuestion] = useState(''); const [streaming, setStreaming] = useState(false); const [draft, setDraft] = useState<Message | null>(null); const [submittedQuestion, setSubmittedQuestion] = useState<string | null>(null); const [error, setError] = useState<Error | null>(null)
  const controller = useRef<AbortController | null>(null); const mounted = useRef(true); const messageList = useRef<HTMLDivElement | null>(null); const following = useRef(true)
  const history = useQuery({ queryKey: ['messages', chat.id], queryFn: () => api<Collection<Message>>(`/chats/${chat.id}/messages`), refetchInterval: (query) => !streaming && query.state.data?.items.some((message) => message.state === 'processing') ? 1500 : false })
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; controller.current?.abort() } }, [])
  useEffect(() => { if (following.current && messageList.current) messageList.current.scrollTop = messageList.current.scrollHeight }, [draft?.content, history.data, submittedQuestion])
  const sending = streaming || history.data?.items.some((message) => message.state === 'processing')
  async function send() {
    const content = question.trim(); if (!content || sending || !allowed) return
    const abort = new AbortController(); controller.current = abort; setStreaming(true); setError(null); setDraft(null); setSubmittedQuestion(content); setQuestion(''); let terminal = false
    try {
      const response = await checkedResponse(`/chats/${chat.id}/messages/stream`, { ...json('POST', { content, ...settings, request_id: crypto.randomUUID() } satisfies ChatInput), signal: abort.signal })
      await readEvents(response, (event) => {
        if (!mounted.current) return
        if (terminal) throw new Error('The server sent events after the response completed. Reload the conversation.')
        if (event.event === 'message.started') setDraft({ id: event.data.message_id, role: 'assistant', content: '', state: 'processing', model: settings.model, reasoning_effort: settings.reasoning_effort, citations: [], created_at: new Date().toISOString() })
        if (event.event === 'message.delta') setDraft((previous) => previous ? { ...previous, content: previous.content + event.data.text } : { id: 'stream', role: 'assistant', content: event.data.text, state: 'processing', model: settings.model, reasoning_effort: settings.reasoning_effort, citations: [], created_at: new Date().toISOString() })
        if (event.event === 'message.completed') { if (event.data.citations.some((citation) => citation.document_id !== chat.document_id)) throw new Error('The response included a source outside this document.'); terminal = true; setDraft(event.data) }
        if (event.event === 'message.failed') { terminal = true; setError(new Error(event.data.message)); setDraft((previous) => previous ? { ...previous, state: 'failed' } : null) }
      })
      if (!terminal) throw new Error('The response ended early. Your question was not automatically sent again. Reload the conversation to check its saved state.')
    } catch (caught) {
      if (mounted.current) { setError(caught instanceof DOMException && caught.name === 'AbortError' ? new Error('Generation stopped. The saved conversation will show any partial answer.') : caught instanceof Error ? caught : new Error('The response failed. Reload the conversation.')); setDraft((previous) => previous ? { ...previous, state: 'interrupted' } : null) }
    } finally {
      controller.current = null
      if (mounted.current) { setStreaming(false); const refreshed = await history.refetch(); if (refreshed.data) { const saved = refreshed.data.items; if (saved.some((message) => message.role === 'user' && message.content === content)) setSubmittedQuestion(null); setDraft((previous) => previous && saved.some((message) => message.id === previous.id) ? null : previous) }; void client.invalidateQueries({ queryKey: ['chats', chat.paper_id] }) }
    }
  }
  const messages = history.data?.items ?? []; const showDraft = draft && !messages.some((message) => message.id === draft.id)
  return <section className="conversation" aria-label={chat.title}><h3>{chat.title}</h3><ErrorNotice error={history.error} retry={() => void history.refetch()}/>{history.isPending && <Loading>Loading conversation…</Loading>}<div className="message-list" ref={messageList} onScroll={() => { const element = messageList.current; if (element) following.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80 }} tabIndex={0} aria-label="Conversation messages">{!messages.length && !draft && !submittedQuestion && !history.isPending && <p className="muted">Ask about the methods, results, or a passage in this paper.</p>}{messages.map((message) => <article className={`message message-${message.role}`} key={message.id}><div className="message-heading"><strong>{message.role === 'user' ? 'You' : 'Assistant'}</strong>{message.state !== 'completed' && <span className="status">{message.state}</span>}</div><ResponseMetadata message={message}/><GeneratedContent content={message.content || (message.state === 'processing' ? 'Preparing a response…' : 'No answer was saved.')}/><Citations citations={message.citations} documentId={chat.document_id}/></article>)}{submittedQuestion && <article className="message message-user"><strong>You</strong><p className="generated-content">{submittedQuestion}</p></article>}{showDraft && <article className="message message-assistant"><div className="message-heading"><strong>Assistant</strong><span className="status">{draft.state}</span></div><ResponseMetadata message={draft}/><GeneratedContent content={draft.content || 'Preparing a response…'}/><Citations citations={draft.citations} documentId={chat.document_id}/></article>}</div><div aria-live="polite" className="sr-only">{streaming ? 'Assistant is responding.' : draft?.state === 'completed' ? 'Response complete.' : ''}</div><ErrorNotice error={error}/><form className="question-form" onSubmit={(event) => { event.preventDefault(); void send() }}><div className="field"><label htmlFor="paper-question">Question about this paper</label><textarea id="paper-question" rows={3} value={question} maxLength={8000} onChange={(event) => setQuestion(event.target.value)} disabled={!allowed || !!sending || history.isPending}/></div><div className="button-row"><Button type="submit" disabled={!allowed || !!sending || history.isPending || !question.trim()}>Ask question</Button>{streaming && <Button type="button" variant="outline" onClick={() => controller.current?.abort()}>Stop generation</Button>}</div></form></section>
}
export function ChatPanel({ paper, settings, allowed }: { paper: Paper; settings: GenerationSettings; allowed: boolean }) {
  const client = useQueryClient(); const [selected, setSelected] = useState<string | null>(null); const chats = useQuery({ queryKey: ['chats', paper.id], queryFn: () => api<Collection<Chat>>(`/papers/${paper.id}/chats`) }); const create = useMutation({ mutationFn: () => api<Chat>(`/papers/${paper.id}/chats`, json('POST', {})), onSuccess: (chat) => { client.setQueryData<Collection<Chat>>(['chats', paper.id], (previous) => ({ items: [chat, ...(previous?.items ?? [])] })); setSelected(chat.id) } }); const current = chats.data?.items.find((chat) => chat.id === selected)
  return <div><div className="panel-heading"><h2>Paper questions</h2><Button variant="outline" disabled={paper.document_status !== 'ready' || create.isPending} onClick={() => create.mutate()}>{create.isPending ? 'Creating…' : 'New conversation'}</Button></div><p className="muted small">Each conversation stays linked to the PDF used when it was created.</p><ErrorNotice error={chats.error || create.error} retry={() => void chats.refetch()}/>{chats.isPending && <Loading>Loading conversations…</Loading>}{chats.data && (chats.data.items.length ? <div className="conversation-layout"><div className="conversation-list" aria-label="Saved conversations">{chats.data.items.map((chat) => <Button key={chat.id} variant={selected === chat.id ? 'outline' : 'ghost'} className="conversation-link" onClick={() => setSelected(chat.id)} aria-pressed={selected === chat.id}>{chat.title || 'Untitled conversation'}{chat.document_id !== paper.active_document_id && <span className="small">Earlier PDF</span>}</Button>)}</div>{current ? <Conversation key={current.id} chat={current} settings={settings} allowed={allowed}/> : <Empty title="Open a conversation">Choose a saved conversation or start a new one.</Empty>}</div> : <Empty title="No conversations yet">Start a conversation to ask a question about this paper.</Empty>)}</div>
}
