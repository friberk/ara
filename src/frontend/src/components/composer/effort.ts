const effortLabels: Record<string, string> = { default: 'Runtime preset', none: 'None', on: 'Reasoning enabled', minimal: 'Minimal', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high', max: 'Max' }

/** Reader-facing name for a reasoning effort id. */
export const effortLabel = (effort: string) => effortLabels[effort] ?? effort
