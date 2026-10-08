import { useEffect, useState } from 'react'

const formatter = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
const units: [Intl.RelativeTimeFormatUnit, number][] = [['year', 31_557_600], ['month', 2_629_800], ['week', 604_800], ['day', 86_400], ['hour', 3_600], ['minute', 60]]

/** "5 minutes ago", "yesterday"; anything under a minute is "just now". Null for an unreadable timestamp. */
export function relativeTime(iso: string | null | undefined, now: number): string | null {
  const time = iso ? Date.parse(iso) : Number.NaN
  if (Number.isNaN(time)) return null
  const seconds = (time - now) / 1000
  const unit = units.find(([, size]) => Math.abs(seconds) >= size)
  return unit ? formatter.format(Math.round(seconds / unit[1]), unit[0]) : 'just now'
}

export const absoluteTime = new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeStyle: 'short' })

/** The current time, refreshed on an interval so relative labels do not go stale on an idle page. */
export function useNow(intervalMs = 30_000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(timer)
  }, [intervalMs])
  return now
}
