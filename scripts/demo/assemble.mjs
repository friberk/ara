// Turns a recorded run into the finished video: trims and time-lapses each clip, adds the title cards with
// fades through black, and joins everything into one 1080p MP4 with a silent audio track (ARA-113).
// Usage: node assemble.mjs --run <id>
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { parseArgs } from 'node:util'
import { fileURLToPath } from 'node:url'
import ffmpeg from 'ffmpeg-static'

import { clips } from './clips/index.mjs'
import { FRAME, OUT, VIDEO, VIEWPORT } from './lib/config.mjs'
import { pngSize, render } from './lib/render.mjs'
import { badgeWindows, clipFilter, outputDuration, planSegments } from './lib/timeline.mjs'

const { values } = parseArgs({ options: { run: { type: 'string' } } })
if (!values.run) throw new Error('usage: node assemble.mjs --run <id>')
const here = path.dirname(fileURLToPath(import.meta.url))
const runDir = path.join(OUT, values.run)
const timeline = JSON.parse(fs.readFileSync(path.join(runDir, 'timeline.json'), 'utf8'))
const cards = JSON.parse(fs.readFileSync(path.join(here, 'cards.json'), 'utf8'))
const dirs = Object.fromEntries(
  ['raw', 'clips', 'cards', 'badges', 'pieces'].map((name) => [name, path.join(runDir, name)]),
)
for (const dir of Object.values(dirs)) fs.mkdirSync(dir, { recursive: true })

const CARD_SECONDS = 3
const FADE = 0.5
const encode = ['-c:v', 'libx264', '-preset', 'slow', '-crf', '18', '-pix_fmt', 'yuv420p', '-video_track_timescale', '90000']

function run(args, label) {
  const result = spawnSync(ffmpeg, ['-hide_banner', '-loglevel', 'error', '-y', ...args], { encoding: 'utf8' })
  if (result.status !== 0) throw new Error(`ffmpeg failed (${label}):\n${result.stderr}`)
}

// Duration, size and frame rate from ffmpeg's stream summary; no ffprobe needed.
function probe(file) {
  const result = spawnSync(ffmpeg, ['-hide_banner', '-i', file], { encoding: 'utf8' })
  const text = result.stderr
  const duration = text.match(/Duration: (\d+):(\d+):([\d.]+)/)
  const video = text.match(/Video: .*?, (\d{2,5})x(\d{2,5})[ ,].*?([\d.]+) fps/)
  if (!duration || !video) throw new Error(`could not read ${file}:\n${text}`)
  return {
    duration: Number(duration[1]) * 3600 + Number(duration[2]) * 60 + Number(duration[3]),
    width: Number(video[1]),
    height: Number(video[2]),
    fps: Number(video[3]),
  }
}

const recorded = clips.filter((clip) => timeline.clips[clip.id])
const missing = clips.filter((clip) => !timeline.clips[clip.id]).map((clip) => clip.id)
if (missing.length) console.warn(`warning: not recorded yet, left out: ${missing.join(', ')}`)
if (recorded.length === 0) throw new Error('no recorded clips in this run')

const plans = recorded.map((clip) => {
  const entry = timeline.clips[clip.id]
  const file = path.join(dirs.raw, entry.video)
  const info = probe(file)
  const segments = planSegments({ duration: info.duration, start: entry.start, end: entry.end, lapses: entry.lapses })
  return { id: clip.id, file, info, segments }
})
const fps = Math.round(plans[0].info.fps)
const factors = [...new Set(plans.flatMap((plan) => plan.segments.map((s) => s.factor)).filter((f) => f > 1))]

console.log('rendering title cards and badges')
const art = await render({
  cards,
  clipIds: recorded.map((clip) => clip.id),
  factors,
  cardsDir: dirs.cards,
  badgesDir: dirs.badges,
})

function encodeCard(png, out) {
  run(
    [
      '-loop', '1', '-framerate', String(fps), '-t', String(CARD_SECONDS), '-i', png,
      '-vf', `fade=t=in:st=0:d=${FADE},fade=t=out:st=${CARD_SECONDS - FADE}:d=${FADE},format=yuv420p,setsar=1`,
      '-r', String(fps), ...encode, out,
    ],
    path.basename(png),
  )
  return out
}

function encodeClip(plan) {
  const { width, height } = plan.info
  // The badge sits at the right end of testreel's title bar, inside the window frame.
  const left = Math.round((VIDEO.width - width) / 2 + (width - VIEWPORT.width) / 2)
  const barTop = Math.round((VIDEO.height - height) / 2 + (height - VIEWPORT.height - FRAME.titleBar) / 2)
  const used = [...new Set(plan.segments.map((s) => s.factor).filter((f) => f > 1))]
  const badges = used.map((factor, i) => {
    const size = pngSize(art.badges[factor])
    return {
      input: i + 1,
      factor,
      file: art.badges[factor],
      x: left + VIEWPORT.width - size.width - 14,
      y: barTop + Math.round((FRAME.titleBar - size.height) / 2),
    }
  })
  const graph = clipFilter(plan.segments, {
    fps,
    size: VIDEO,
    background: `0x${FRAME.background.slice(1)}`,
    fade: FADE,
    badges,
  })
  const out = path.join(dirs.clips, `${plan.id}.mp4`)
  run(
    [
      '-i', plan.file,
      ...badges.flatMap((badge) => ['-loop', '1', '-framerate', String(fps), '-i', badge.file]),
      '-filter_complex', graph, '-map', '[out]', '-r', String(fps), ...encode, '-an', out,
    ],
    plan.id,
  )
  return out
}

const pieces = [encodeCard(art.cards.opening, path.join(dirs.pieces, '00-opening.mp4'))]
const report = []
for (const plan of plans) {
  console.log(`encoding ${plan.id}`)
  pieces.push(encodeCard(art.cards[plan.id], path.join(dirs.pieces, `${plan.id}-card.mp4`)))
  pieces.push(encodeClip(plan))
  report.push({
    id: plan.id,
    recorded: Number(plan.info.duration.toFixed(1)),
    final: Number(outputDuration(plan.segments).toFixed(1)),
    lapses: badgeWindows(plan.segments).map((w) => `${w.factor}x at ${w.from.toFixed(1)}s`),
  })
}
pieces.push(encodeCard(art.cards.closing, path.join(dirs.pieces, '99-closing.mp4')))

const list = path.join(runDir, 'concat.txt')
fs.writeFileSync(list, pieces.map((file) => `file '${file.replace(/'/g, "'\\''")}'`).join('\n') + '\n')
const master = path.join(runDir, 'ara-demo.mp4')
console.log('joining')
run(
  [
    '-f', 'concat', '-safe', '0', '-i', list,
    '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
    '-map', '0:v', '-map', '1:a', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '96k', '-shortest',
    '-movflags', '+faststart', master,
  ],
  'concat',
)

const final = probe(master)
fs.writeFileSync(path.join(runDir, 'assembly.json'), `${JSON.stringify({ fps, clips: report, master: final }, null, 2)}\n`)
console.table(report.map(({ lapses, ...row }) => ({ ...row, lapses: lapses.join(', ') })))
console.log(`\n${master}\n${final.width}x${final.height}, ${final.fps} fps, ${final.duration.toFixed(1)} s`)
