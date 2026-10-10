import { useEffect, useState } from 'react'

const minute = 60_000
const hour = 3_600_000
const day = 86_400_000
const monthDay = new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric' })
const monthDayYear = new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', year: 'numeric' })
const longMonthDay = new Intl.DateTimeFormat('en', { month: 'long', day: 'numeric' })
const longMonthDayYear = new Intl.DateTimeFormat('en', { month: 'long', day: 'numeric', year: 'numeric' })
const full = new Intl.DateTimeFormat('en', { dateStyle: 'long', timeStyle: 'short' })

type Elapsed = { kind: 'now' } | { kind: 'ago'; unit: 'minute' | 'hour' | 'day'; count: number } | { kind: 'date'; date: Date; sameYear: boolean }

/** Relative up to six days, a calendar date from seven (NN/g): the year is dropped only for the current one. */
function elapsed(iso: string | null | undefined, now: number): Elapsed | null {
  const time = iso ? Date.parse(iso) : Number.NaN
  if (Number.isNaN(time)) return null
  const age = Math.max(0, now - time)
  if (age < minute) return { kind: 'now' }
  if (age < hour) return { kind: 'ago', unit: 'minute', count: Math.floor(age / minute) }
  if (age < day) return { kind: 'ago', unit: 'hour', count: Math.floor(age / hour) }
  if (age < 7 * day) return { kind: 'ago', unit: 'day', count: Math.floor(age / day) }
  const date = new Date(time)
  return { kind: 'date', date, sameYear: date.getFullYear() === new Date(now).getFullYear() }
}

/** "now", "12m", "3h", "2d", then "Oct 2" this year and "Oct 2, 2025" before. Null for an unreadable timestamp. */
export function compactRelativeTime(iso: string | null | undefined, now: number): string | null {
  const value = elapsed(iso, now)
  if (!value) return null
  if (value.kind === 'now') return 'now'
  if (value.kind === 'ago') return `${value.count}${value.unit === 'minute' ? 'm' : value.unit === 'hour' ? 'h' : 'd'}`
  return (value.sameYear ? monthDay : monthDayYear).format(value.date)
}

/** The spoken form of the compact label: "12 minutes ago", "3 days ago", "October 2". */
export function longRelativeTime(iso: string | null | undefined, now: number): string | null {
  const value = elapsed(iso, now)
  if (!value) return null
  if (value.kind === 'now') return 'just now'
  if (value.kind === 'ago') return `${value.count} ${value.unit}${value.count === 1 ? '' : 's'} ago`
  return (value.sameYear ? longMonthDay : longMonthDayYear).format(value.date)
}

/** The exact local date and time, for a hover title. */
export function fullDateTime(iso: string | null | undefined): string | null {
  const time = iso ? Date.parse(iso) : Number.NaN
  return Number.isNaN(time) ? null : full.format(time)
}

/** The current time, refreshed on an interval so relative labels do not go stale on an idle page. */
export function useNow(intervalMs = 30_000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
  return now
}
