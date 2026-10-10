/**
 * Uploads use XMLHttpRequest for real progress (ARA-086). jsdom's own would reach the network, so tests send it
 * through fetch instead: mockApi routes answer it, and upload progress reports half the body, then all of it.
 */
export class FetchBackedXhr {
  upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null
  status = 0
  responseText = ''
  private method = 'GET'
  private url = ''
  private readonly controller = new AbortController()

  open(method: string, url: string) { this.method = method; this.url = url }
  setRequestHeader() {}
  send(body?: XMLHttpRequestBodyInit | null) {
    const total = body instanceof FormData ? [...body.values()].reduce((sum, value) => sum + (value instanceof Blob ? value.size : value.length), 0) : 0
    const progress = (loaded: number) => this.upload.onprogress?.({ lengthComputable: true, loaded, total } as ProgressEvent)
    queueMicrotask(() => progress(Math.round(total / 2)))
    fetch(this.url, { method: this.method, body, signal: this.controller.signal }).then(async (response) => {
      if (this.controller.signal.aborted) return
      progress(total)
      this.status = response.status
      this.responseText = await response.text()
      this.onload?.()
    }, () => { if (!this.controller.signal.aborted) this.onerror?.() })
  }
  abort() { this.controller.abort(); this.onabort?.() }
}
