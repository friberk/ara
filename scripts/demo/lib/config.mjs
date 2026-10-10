import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const repo = path.resolve(here, '../../..')
const commonDir = execFileSync('git', ['-C', repo, 'rev-parse', '--path-format=absolute', '--git-common-dir'], {
  encoding: 'utf8',
}).trim()

// Generated output lives in the main checkout's ignored evidence folder, so it outlives this worktree.
export const ROOT = path.dirname(commonDir)
export const REPO = repo
export const OUT = process.env.DEMO_OUT ?? path.join(ROOT, 'docs/evidence/generated/demo')
export const INPUTS = path.join(OUT, 'inputs')
export const APP = process.env.DEMO_APP_URL ?? 'http://localhost:5182'
export const API = process.env.DEMO_API_URL ?? 'http://127.0.0.1:8012'

export const VIEWPORT = { width: 1600, height: 900 }
export const FRAME = { padding: 60, titleBar: 38, background: '#0a0a0a' }
export const VIDEO = { width: 1920, height: 1080 }

export const QUERY = 'regular expression denial of service'

// Cards are found by DOI link, never by position: OpenAlex's order can change between days.
export const PAPERS = {
  fse: {
    doi: '10.1145/3236024.3236027',
    title: 'The impact of regular expression denial of service (ReDoS) in practice',
  },
  sok: {
    doi: '10.1145/3708821.3733912',
    title: 'SoK: A Literature and Engineering Review of Regular Expression Denial of Service',
    file: path.join(INPUTS, '2406.11618v4.pdf'),
  },
  backrefs: {
    title: 'Regular Expression Denial of Service Induced by Backreferences',
    file: path.join(INPUTS, 'usenixsecurity26-liu-yichen.pdf'),
  },
}

export function runId() {
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`
}
