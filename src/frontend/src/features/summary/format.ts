import { effortLabel } from '@/components/composer/ModelSwitcher'

export function effortText(effort: string) { return effort === 'none' ? 'No reasoning' : `${effortLabel(effort)} reasoning` }

const timestamp = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
export function formatTimestamp(iso: string) {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : timestamp.format(date)
}
