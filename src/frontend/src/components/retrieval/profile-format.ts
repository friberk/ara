import type { EmbeddingProfile } from '@/api/types'

/** What a search model costs: hosted models by the million tokens, local models nothing. */
export function priceLabel(profile: Pick<EmbeddingProfile, 'provider' | 'price_per_million'>) {
  return profile.price_per_million > 0 ? `$${profile.price_per_million} per million tokens` : profile.provider === 'ollama' ? 'Runs locally. No per-token cost.' : null
}
