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
/** `duplicate` is set by uploads; a retrieval hand-off to processing leaves it out (ARA-086). */
export type UploadAccepted = Omit<Schemas['UploadAccepted'], 'duplicate'> & { duplicate?: boolean }
export type FullTextStatus = Schemas['FullTextStatus']
export type FullTextAccepted = Schemas['FullTextAccepted']
export type FullTextInput = Schemas['FullTextInput']
export type AutomaticFullText = Schemas['AutomaticFullText']
export type Job = Schemas['JobStatus']
export type Citation = Schemas['app__schemas__ai__Citation']
export type Summary = Schemas['Summary']
export type SummaryAccepted = Schemas['SummaryAccepted']
export type SummaryPage = Schemas['SummaryPage']
export type SummaryBlock = Schemas['SummaryBlock']
export type Chat = Schemas['Chat']
export type Message = Schemas['Message']
export type Model = Schemas['Model']
export type ModelInstallation = Schemas['Installation']
export type Settings = Schemas['Defaults']
/** Server features, such as experimental open models (ARA-090). */
export type Features = Schemas['Features']
export type SettingsUpdate = Settings
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
export type ReindexEstimate = Schemas['ReindexEstimate']
export type ChatMemory = Schemas['ChatMemoryOut']
export type ChatMemoryState = Schemas['ChatMemoryState']
// The composer's context and cost meter (ARA-085).
export type ChatUsage = Schemas['ChatUsage']
export type ChatCost = Schemas['ChatCost']
/**
 * `waiting`: background local work holds the runtime; the question waits up to a minute for it.
 * `widening`: the first answer found too little, so the one wider retry replaces it (ARA-094).
 * `mapping`: a small window reads each paper in its own request before answering.
 */
export type RetrievalStage = 'waiting' | 'planning' | 'retrieving' | 'reranking' | 'generating' | 'widening' | 'mapping'
export type Reranker = Schemas['RerankerOut']
export type RerankerKey = NonNullable<RetrievalSettings['reranker']>

// Uploaded-paper metadata lookups (ARA-086, docs/api-contract.md).
export type MetadataSettings = Schemas['MetadataSettings']
export type MetadataSource = MetadataSettings['source']
export type UploadMatch = Schemas['UploadMatch']
export type PaperLink = Schemas['PaperLink']
export type MatchDecision = Schemas['MatchDecision']['decision']
// Chats over several library papers (ARA-088, docs/api-contract.md).
export type IncludedPaper = Schemas['IncludedPaper']
// Deleting papers and their preview (ARA-095, docs/api-contract.md).
export type DeletionPreview = Schemas['DeletionPreview']
export type DeletedPapers = Schemas['DeletedPapers']
