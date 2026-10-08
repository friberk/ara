import { readEvents } from './sse'

function fragmented(text: string) {
  const bytes = new TextEncoder().encode(text)
  return new Response(new ReadableStream<Uint8Array>({ start(controller) { for (const byte of bytes) controller.enqueue(new Uint8Array([byte])); controller.close() } }), { headers: { 'Content-Type': 'text/event-stream' } })
}

test('Given fragmented UTF-8 and multiple frames, When read, Then every event retains its data', async () => {
  const events: { event: string; data: unknown }[] = []
  await readEvents(fragmented(': keepalive\r\n\r\nevent: message.started\r\ndata: {"message_id":"a"}\r\n\r\nevent: message.delta\ndata: {"text":"café 🔬"}\n\nevent: message.failed\ndata: {"code":"provider_error","message":"Try again"}\n\n'), (event) => events.push(event))
  expect(events).toEqual([{ event: 'message.started', data: { message_id: 'a' } }, { event: 'message.delta', data: { text: 'café 🔬' } }, { event: 'message.failed', data: { code: 'provider_error', message: 'Try again' } }])
})

test.each(['event: surprise\ndata: {}\n\n', 'event: message.delta\ndata: nope\n\n', 'event: message.delta\ndata: {"text":3}\n\n', 'event: message.delta\ndata: {"text":"unfinished"}'])('Given invalid SSE, Then a visible-error-ready exception is raised: %s', async (frame) => {
  await expect(readEvents(fragmented(frame), () => undefined)).rejects.toThrow()
})

test('Given a final heartbeat followed by an incomplete event, Then framing failure is reported', async () => {
  await expect(readEvents(fragmented(': keepalive\nevent: message.delta\ndata: {"text":"lost"}'), () => undefined)).rejects.toThrow('ended')
})
