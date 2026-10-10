import { API } from './config.mjs'

// Read-only lookups against the demo stack. GET requests carry no Origin, so the API's origin check doesn't apply.
export async function get(pathname) {
  const response = await fetch(`${API}/api/v1${pathname}`)
  if (!response.ok) throw new Error(`GET ${pathname} -> ${response.status}`)
  return response.json()
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// Off camera: let every background job finish so the next clip starts from an idle worker.
export async function waitIdle({ timeoutMs = 15 * 60_000, log = console.log } = {}) {
  const started = Date.now()
  let announced = false
  while (Date.now() - started < timeoutMs) {
    const { items } = await get('/jobs?active=true')
    if (items.length === 0) {
      if (announced) log(`  worker idle after ${((Date.now() - started) / 1000).toFixed(0)} s`)
      return
    }
    if (!announced) {
      log(`  waiting for ${items.length} job(s): ${items.map((job) => job.kind).join(', ')}`)
      announced = true
    }
    await sleep(2000)
  }
  throw new Error('background jobs did not finish in time')
}

export async function papers() {
  return (await get('/papers?limit=100')).items
}

export async function paperByDoi(doi) {
  const found = (await papers()).find((paper) => paper.doi?.toLowerCase() === doi.toLowerCase())
  if (!found) throw new Error(`no library paper with DOI ${doi}`)
  return found
}

export async function paperByTitle(prefix) {
  const found = (await papers()).find((paper) => paper.title?.toLowerCase().startsWith(prefix.toLowerCase()))
  if (!found) throw new Error(`no library paper titled "${prefix}…"`)
  return found
}

export async function chats() {
  const body = await get('/chats?limit=100')
  return body.items ?? body
}
