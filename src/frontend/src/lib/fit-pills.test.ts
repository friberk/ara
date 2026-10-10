import { fitPills } from './fit-pills'

test('Given widths that all fit on one line, Then every pill shows and there is no +N', () => {
  expect(fitPills([100, 100, 100], 320, 30, 8)).toBe(3)
})

test('Given too little room, Then as many pills show as fit beside the +N pill', () => {
  // 100 + 8 + 100 + 8 + 30 = 246 fits in 250; a third pill would not.
  expect(fitPills([100, 100, 100, 100], 250, 30, 8)).toBe(2)
})

test('Given almost no room, Then one pill still shows', () => {
  expect(fitPills([200, 200, 200], 50, 30, 8)).toBe(1)
})

test('Given no paper, Then none show', () => {
  expect(fitPills([], 300, 30, 8)).toBe(0)
})
