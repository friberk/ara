import type { components } from './generated'
// Aliases keep UI names stable while OpenAPI remains the contract authority.
type Schemas = components['schemas']
export type Provider = Schemas['SearchResult']['provider']
export interface Collection<T> { items: T[] }
export type SearchResult = Schemas['SearchResult']
export type SearchPage = Schemas['SearchPage']
export type Paper = Schemas['PaperDetail']
export type PaperPatch = Schemas['PaperPatch']
export type SavePaper = Schemas['SavePaper']
export type UploadAccepted = Schemas['UploadAccepted']
export type Job = Schemas['JobStatus']
export type Citation = Schemas['app__schemas__ai__Citation']
export type Summary = Schemas['Summary']
export type SummaryAccepted = Schemas['SummaryAccepted']
export type Chat = Schemas['Chat']
export type Message = Schemas['Message']
export type Model = Schemas['Model']
export type Settings = Schemas['Defaults']
export type GenerationInput = Schemas['GenerationInput']
export type ChatInput = Schemas['ChatInput']
export type GenerationSettings = Pick<GenerationInput, 'model' | 'reasoning_effort'>
export type DocumentState = Paper['document_status']

// Workspace history additions (ARA-034, docs/api-contract.md). Written from the contract until
// generated.ts is regenerated from the merged API; then these become Schemas aliases.
export type TitleSource = 'default' | 'auto' | 'manual'
export type ChatSummary = Chat & { title_source?: TitleSource; paper_title: string | null; last_activity_at: string; message_count: number; last_question_preview: string | null }
export interface SearchHistoryItem { id: string; provider: Provider; query: string; created_at: string; last_searched_at: string }
export type SearchHit = SearchResult & { saved_paper_id?: string | null }
export type JobView = Job & { paper_id?: string | null; paper_title?: string | null }
export const providerLabels: Record<Provider, string> = { openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar' }
