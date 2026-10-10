// Pure timeline logic for the demo video: which parts of a clip play at 1x,
// which waits are time-lapsed, and the ffmpeg filtergraph that does it.
// All times are seconds on the recorded clip's own timeline.

export const DEFAULTS = { keepAfterChange: 2.5, lapseTarget: 2, maxFactor: 30, minGap: 4, minWindow: 1 }

const round = (x) => Math.round(x * 1000) / 1000
const fmt = (x) => String(Number(x.toFixed(6)))

function mergeRanges(ranges) {
  const sorted = ranges.filter(([a, b]) => b > a).sort((x, y) => x[0] - y[0])
  const merged = []
  for (const [a, b] of sorted) {
    const last = merged.at(-1)
    if (last && a <= last[1]) last[1] = Math.max(last[1], b)
    else merged.push([a, b])
  }
  return merged
}

// Splits one wait into kept (1x) ranges and compressible gaps. Each wait keeps
// its first moments and the moments after every status-label change, so each
// step stays readable; gaps shorter than minGap aren't worth a badge and stay at 1x.
function lapseGaps(lapse, options) {
  const { keepAfterChange, minGap } = options
  const changes = [lapse.start, ...(lapse.changes ?? []).filter((t) => t > lapse.start && t < lapse.end)]
  const kept = mergeRanges(changes.map((t) => [t, Math.min(lapse.end, t + keepAfterChange)]))
  const gaps = []
  let cursor = lapse.start
  for (const [a, b] of kept) {
    if (a - cursor >= minGap) gaps.push([cursor, a])
    cursor = b
  }
  if (lapse.end - cursor >= minGap) gaps.push([cursor, lapse.end])
  return gaps
}

export function planSegments(clip, options = DEFAULTS) {
  const opts = { ...DEFAULTS, ...options }
  const start = clip.start ?? 0
  const end = Math.min(clip.end ?? clip.duration, clip.duration)
  if (!(start < end)) throw new Error(`clip start ${start} must be before its end ${end}`)

  const lapses = mergeRanges(
    (clip.lapses ?? []).map((l) => [Math.max(start, l.start), Math.min(end, l.end)]),
  ).map(([a, b]) => ({
    start: a,
    end: b,
    changes: (clip.lapses ?? []).flatMap((l) => l.changes ?? []),
  }))

  const fast = []
  for (const lapse of lapses) {
    const gaps = lapseGaps(lapse, opts)
    const compressible = gaps.reduce((sum, [a, b]) => sum + (b - a), 0)
    const factor = Math.min(opts.maxFactor, Math.round(compressible / opts.lapseTarget))
    if (factor < 2) continue
    // One speed per wait, except that no stretch may flash by in under minWindow seconds.
    for (const [a, b] of gaps) {
      const own = Math.min(factor, Math.floor((b - a) / opts.minWindow))
      if (own >= 2) fast.push({ from: a, to: b, factor: own })
    }
  }

  const segments = []
  let cursor = start
  for (const gap of fast) {
    if (gap.from > cursor) segments.push({ from: cursor, to: gap.from, factor: 1 })
    segments.push(gap)
    cursor = gap.to
  }
  if (end > cursor) segments.push({ from: cursor, to: end, factor: 1 })

  return segments
    .map((s) => ({ from: round(s.from), to: round(s.to), factor: s.factor }))
    .filter((s) => s.to > s.from)
}

export function outputDuration(segments) {
  return segments.reduce((sum, s) => sum + (s.to - s.from) / s.factor, 0)
}

export function mapTime(segments, t) {
  let out = 0
  for (const s of segments) {
    if (t <= s.to) return out + (Math.max(t, s.from) - s.from) / s.factor
    out += (s.to - s.from) / s.factor
  }
  return out
}

export function badgeWindows(segments) {
  const windows = []
  let out = 0
  for (const s of segments) {
    const length = (s.to - s.from) / s.factor
    if (s.factor > 1) windows.push({ from: out, to: out + length, factor: s.factor })
    out += length
  }
  return windows
}

// Piecewise map from the input frame time T to output seconds, for setpts.
export function setptsExpression(segments) {
  let offset = 0
  const pieces = segments.map((s) => {
    const piece = `${fmt(offset)}+(T-${fmt(s.from)})/${s.factor}`
    offset += (s.to - s.from) / s.factor
    return { piece, to: s.to }
  })
  return pieces
    .slice(0, -1)
    .reduceRight((rest, { piece, to }) => `if(lt(T,${fmt(to)}),${piece},${rest})`, pieces.at(-1).piece)
}

// One streaming pass per clip: trim, retime with a piecewise setpts, resample,
// pad onto the 1080p background, show the "sped up" badge only while
// compressed, and fade through black at both ends.
export function clipFilter(segments, { fps, size, background, fade, badges }) {
  const first = segments[0].from
  const last = segments.at(-1).to
  const duration = outputDuration(segments)
  const windows = badgeWindows(segments)

  const parts = [
    `[0:v]trim=start=${fmt(first)}:end=${fmt(last)},setpts='(${setptsExpression(segments)})/TB',fps=${fps},` +
      `pad=${size.width}:${size.height}:(ow-iw)/2:(oh-ih)/2:color=${background},setsar=1[base];`,
  ]
  let current = 'base'
  badges
    .map((badge) => ({ badge, active: windows.filter((w) => w.factor === badge.factor) }))
    .filter(({ active }) => active.length > 0)
    .forEach(({ badge, active }, i) => {
      const enable = active.map((w) => `between(t,${fmt(w.from)},${fmt(w.to)})`).join('+')
      parts.push(`[${current}][${badge.input}:v]overlay=x=${badge.x}:y=${badge.y}:shortest=1:enable='${enable}'[b${i}];`)
      current = `b${i}`
    })
  parts.push(
    `[${current}]fade=t=in:st=0:d=${fmt(fade)},fade=t=out:st=${fmt(duration - fade)}:d=${fmt(fade)},format=yuv420p[out]`,
  )
  return parts.join('')
}
