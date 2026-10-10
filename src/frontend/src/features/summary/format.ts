import { effortLabel } from '@/components/composer/effort'

export function effortText(effort: string) { return effort === 'none' ? 'No reasoning' : effort === 'default' || effort === 'on' ? effortLabel(effort) : `${effortLabel(effort)} reasoning` }
