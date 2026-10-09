const effortLabels: Record<string, string> = { default: 'Model default', none: 'None', on: 'On', minimal: 'Minimal', low: 'Low', medium: 'Medium', high: 'High', xhigh: 'Extra high', max: 'Max' }

/** Reader-facing name for a reasoning effort id. */
export const effortLabel = (effort: string) => effortLabels[effort] ?? effort
