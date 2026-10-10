// Renders the title cards and sample badges for a preview, without assembling the video.
// Usage: node cards.mjs [--run <id>]
import fs from 'node:fs'
import path from 'node:path'
import { parseArgs } from 'node:util'
import { fileURLToPath } from 'node:url'

import { clips } from './clips/index.mjs'
import { OUT } from './lib/config.mjs'
import { render } from './lib/render.mjs'

const { values } = parseArgs({ options: { run: { type: 'string', default: 'cards-preview' } } })
const here = path.dirname(fileURLToPath(import.meta.url))
const cards = JSON.parse(fs.readFileSync(path.join(here, 'cards.json'), 'utf8'))
const runDir = path.join(OUT, values.run)

const written = await render({
  cards,
  clipIds: clips.map((clip) => clip.id),
  factors: [8, 30],
  cardsDir: path.join(runDir, 'cards'),
  badgesDir: path.join(runDir, 'badges'),
})
for (const file of [...Object.values(written.cards), ...Object.values(written.badges)]) console.log(file)
