import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  badgeWindows,
  clipFilter,
  mapTime,
  outputDuration,
  planSegments,
  setptsExpression,
} from './timeline.mjs'

const opts = { keepAfterChange: 2.5, lapseTarget: 2, maxFactor: 30, minGap: 4, minWindow: 1 }

const close = (actual, expected, eps = 1e-6) =>
  assert.ok(Math.abs(actual - expected) < eps, `expected ${expected}, got ${actual}`)

describe('planSegments', () => {
  it('trims the head and keeps everything else at 1x when there are no waits', () => {
    const segments = planSegments({ duration: 20, start: 1.5, lapses: [] }, opts)
    assert.deepEqual(segments, [{ from: 1.5, to: 20, factor: 1 }])
  })

  it('ends at an explicit end mark before the video does', () => {
    const segments = planSegments({ duration: 20, start: 0, end: 18, lapses: [] }, opts)
    assert.deepEqual(segments, [{ from: 0, to: 18, factor: 1 }])
  })

  it('keeps 2.5 s after the wait starts and after each label change, and compresses the rest', () => {
    // A 60 s wait with labels changing at 10 s and 30 s.
    const segments = planSegments(
      { duration: 70, start: 0, lapses: [{ start: 5, end: 65, changes: [10, 30] }] },
      opts,
    )
    // Gaps: 7.5-10 (2.5 s, under 4 s, stays 1x), 12.5-30 (17.5 s), 32.5-65 (32.5 s).
    // 50 s compressible / 2 s target = 25x, capped per stretch so each lasts at least 1 s: 17x and 25x.
    assert.deepEqual(segments, [
      { from: 0, to: 12.5, factor: 1 },
      { from: 12.5, to: 30, factor: 17 },
      { from: 30, to: 32.5, factor: 1 },
      { from: 32.5, to: 65, factor: 25 },
      { from: 65, to: 70, factor: 1 },
    ])
  })

  it('gives every compressed stretch at least a second on screen', () => {
    // Keeps 0-2.5 and 8.5-11; gaps 2.5-8.5 (6 s) and 11-60 (49 s). 55 / 2 = 27.5, so 28x,
    // but the 6 s gap would flash by in 0.2 s, so it runs at 6x instead.
    const segments = planSegments(
      { duration: 60, start: 0, lapses: [{ start: 0, end: 60, changes: [8.5] }] },
      opts,
    )
    assert.deepEqual(segments, [
      { from: 0, to: 2.5, factor: 1 },
      { from: 2.5, to: 8.5, factor: 6 },
      { from: 8.5, to: 11, factor: 1 },
      { from: 11, to: 60, factor: 28 },
    ])
  })

  it('caps the factor so a very long wait still shows motion', () => {
    const segments = planSegments(
      { duration: 400, start: 0, lapses: [{ start: 0, end: 400, changes: [] }] },
      opts,
    )
    assert.deepEqual(segments, [
      { from: 0, to: 2.5, factor: 1 },
      { from: 2.5, to: 400, factor: 30 },
    ])
  })

  it('leaves a short wait at 1x when compressing would save little', () => {
    // Only 1.5 s is compressible, under the 2x threshold.
    const segments = planSegments(
      { duration: 10, start: 0, lapses: [{ start: 2, end: 6, changes: [] }] },
      opts,
    )
    assert.deepEqual(segments, [{ from: 0, to: 10, factor: 1 }])
  })

  it('keeps gaps shorter than minGap at 1x instead of flickering through them', () => {
    // Keeps 10-12.5 and 12.8-15.3 leave a 0.3 s gap (12.5-12.8) that stays at 1x.
    // Only 15.3-40 (24.7 s) is compressed: 24.7 / 2 = 12.35, so 12x.
    const segments = planSegments(
      { duration: 40, start: 0, lapses: [{ start: 10, end: 40, changes: [12.8] }] },
      opts,
    )
    assert.deepEqual(segments, [
      { from: 0, to: 15.3, factor: 1 },
      { from: 15.3, to: 40, factor: 12 },
    ])
  })

  it('clips waits to the trimmed range and ignores waits outside it', () => {
    const segments = planSegments(
      {
        duration: 50,
        start: 4,
        end: 45,
        lapses: [
          { start: 0, end: 3, changes: [] },
          { start: 20, end: 60, changes: [] },
        ],
      },
      opts,
    )
    // The second wait is clipped to 20-45: keep 20-22.5, compress 22.5-45 (22.5 s -> 11x).
    assert.deepEqual(segments, [
      { from: 4, to: 22.5, factor: 1 },
      { from: 22.5, to: 45, factor: 11 },
    ])
  })

  it('ignores label changes that fall outside their wait', () => {
    const segments = planSegments(
      { duration: 30, start: 0, lapses: [{ start: 5, end: 25, changes: [1, 26] }] },
      opts,
    )
    assert.deepEqual(segments, [
      { from: 0, to: 7.5, factor: 1 },
      { from: 7.5, to: 25, factor: 9 },
      { from: 25, to: 30, factor: 1 },
    ])
  })

  it('rejects a start mark beyond the end', () => {
    assert.throws(() => planSegments({ duration: 5, start: 6, lapses: [] }, opts), /start/)
  })
})

describe('outputDuration and mapTime', () => {
  const segments = [
    { from: 2, to: 10, factor: 1 },
    { from: 10, to: 50, factor: 20 },
    { from: 50, to: 55, factor: 1 },
  ]

  it('sums each segment divided by its factor', () => {
    close(outputDuration(segments), 8 + 2 + 5)
  })

  it('maps input times onto the output timeline', () => {
    close(mapTime(segments, 2), 0)
    close(mapTime(segments, 10), 8)
    close(mapTime(segments, 30), 9)
    close(mapTime(segments, 50), 10)
    close(mapTime(segments, 55), 15)
  })
})

describe('badgeWindows', () => {
  it('reports each compressed stretch in output time with its factor', () => {
    const segments = [
      { from: 0, to: 7.5, factor: 1 },
      { from: 7.5, to: 10, factor: 26 },
      { from: 10, to: 12.5, factor: 1 },
      { from: 12.5, to: 65, factor: 26 },
    ]
    const windows = badgeWindows(segments)
    assert.equal(windows.length, 2)
    close(windows[0].from, 7.5)
    close(windows[0].to, 7.5 + 2.5 / 26)
    assert.equal(windows[0].factor, 26)
    close(windows[1].from, 7.5 + 2.5 / 26 + 2.5)
    close(windows[1].to, 7.5 + 2.5 / 26 + 2.5 + 52.5 / 26)
  })

  it('returns nothing when nothing is compressed', () => {
    assert.deepEqual(badgeWindows([{ from: 0, to: 9, factor: 1 }]), [])
  })
})

describe('setptsExpression', () => {
  it('builds a piecewise map from input time T to output seconds', () => {
    const expr = setptsExpression([
      { from: 2, to: 10, factor: 1 },
      { from: 10, to: 50, factor: 20 },
      { from: 50, to: 55, factor: 1 },
    ])
    assert.equal(
      expr,
      'if(lt(T,10),0+(T-2)/1,if(lt(T,50),8+(T-10)/20,10+(T-50)/1))',
    )
  })

  it('handles a single segment', () => {
    assert.equal(setptsExpression([{ from: 1.5, to: 20, factor: 1 }]), '0+(T-1.5)/1')
  })
})

describe('clipFilter', () => {
  const segments = [
    { from: 1, to: 10, factor: 1 },
    { from: 10, to: 50, factor: 20 },
    { from: 50, to: 61, factor: 1 },
  ]

  it('trims, retimes, pads, overlays badges only while compressed, then fades', () => {
    const graph = clipFilter(segments, {
      fps: 25,
      size: { width: 1920, height: 1080 },
      background: '0x0a0a0a',
      fade: 0.5,
      badges: [{ input: 1, factor: 20, x: 1600, y: 80 }],
    })
    assert.equal(
      graph,
      [
        '[0:v]trim=start=1:end=61,setpts=\'(if(lt(T,10),0+(T-1)/1,if(lt(T,50),9+(T-10)/20,11+(T-50)/1)))/TB\',fps=25,',
        'pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0a0a0a,setsar=1[base];',
        "[base][1:v]overlay=x=1600:y=80:shortest=1:enable='between(t,9,11)'[b0];",
        '[b0]fade=t=in:st=0:d=0.5,fade=t=out:st=21.5:d=0.5,format=yuv420p[out]',
      ].join(''),
    )
  })

  it('skips the overlay stage when there are no badges', () => {
    const graph = clipFilter([{ from: 0, to: 8, factor: 1 }], {
      fps: 25,
      size: { width: 1920, height: 1080 },
      background: '0x0a0a0a',
      fade: 0.5,
      badges: [],
    })
    assert.equal(
      graph,
      "[0:v]trim=start=0:end=8,setpts='(0+(T-0)/1)/TB',fps=25,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x0a0a0a,setsar=1[base];" +
        '[base]fade=t=in:st=0:d=0.5,fade=t=out:st=7.5:d=0.5,format=yuv420p[out]',
    )
  })

  it('joins several windows of the same factor into one enable expression', () => {
    const graph = clipFilter(
      [
        { from: 0, to: 2.5, factor: 1 },
        { from: 2.5, to: 12.5, factor: 10 },
        { from: 12.5, to: 15, factor: 1 },
        { from: 15, to: 25, factor: 10 },
      ],
      {
        fps: 25,
        size: { width: 1920, height: 1080 },
        background: '0x0a0a0a',
        fade: 0.5,
        badges: [{ input: 1, factor: 10, x: 10, y: 20 }],
      },
    )
    assert.match(graph, /enable='between\(t,2\.5,3\.5\)\+between\(t,6,7\)'/)
  })
})
