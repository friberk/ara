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
