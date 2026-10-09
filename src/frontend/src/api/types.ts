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
export type ModelInstallation = Schemas['Installation']
export type Settings = Schemas['Defaults']
export type GenerationInput = Schemas['GenerationInput']
export type ChatInput = Schemas['ChatInput']
export type GenerationSettings = Pick<GenerationInput, 'model' | 'reasoning_effort'>
export type DocumentState = Paper['document_status']

// Workspace history additions (ARA-034, docs/api-contract.md).
export type TitleSource = Chat['title_source']
export type ChatSummary = Schemas['ChatSummary']
export type SearchHistoryItem = Schemas['SearchHistoryItem']
export type SearchHit = Schemas['SearchHit']
/** Jobs carry paper_id and paper_title (null when the paper no longer exists). */
export type JobView = Job
export const providerLabels: Record<Provider, string> = { openalex: 'OpenAlex', semantic_scholar: 'Semantic Scholar' }

// Retrieval and conversation context (ARA-070, docs/api-contract.md).
export type ModelKind = Model['kind']
export type RetrievalSummary = Schemas['RetrievalSummary']
export type ContextUsage = Schemas['ContextUsage']
export type Grounding = NonNullable<Message['grounding']>
export type EmbeddingProfile = Schemas['EmbeddingProfileOut']
export type EmbeddingProfilePage = Schemas['EmbeddingProfilePage']
export type RetrievalSettings = Schemas['RetrievalSettings']
export type RetrievalIndex = Schemas['RetrievalIndexOut']
export type PaperRetrieval = Schemas['PaperRetrieval']
export type PaperRetrievalUpdate = Schemas['PaperRetrievalUpdate']
export type ChatMemory = Schemas['ChatMemoryOut']
export type ChatMemoryState = Schemas['ChatMemoryState']
export type RetrievalStage = 'planning' | 'retrieving' | 'reranking' | 'generating'
export type Reranker = Schemas['RerankerOut']
export type RerankerKey = NonNullable<RetrievalSettings['reranker']>
