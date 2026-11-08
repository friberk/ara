// A two-page text PDF of a paper no fixture provider knows, built here so the browser journey needs no extra fixture
// file. Each run gets a new title and new bytes, so it can never match an earlier upload or a library paper.
type Line = { text: string; size: number }

const escaped = (text: string) => text.replace(/[\\()]/g, '\\$&')

function content(lines: Line[]) {
  let y = 720
  return lines.map(({ text, size }) => {
    const row = `BT /F1 ${size} Tf 72 ${y} Td (${escaped(text)}) Tj ET`
    y -= size + 8
    return row
  }).join('\n')
}

function pdf(info: { title: string; author: string }, pages: Line[][]) {
  const pageObjects = pages.flatMap((lines, index) => {
    const stream = content(lines)
    return [
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents ${6 + index * 2} 0 R >>`,
      `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`,
    ]
  })
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    `<< /Type /Pages /Count ${pages.length} /Kids [${pages.map((_, index) => `${5 + index * 2} 0 R`).join(' ')}] >>`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Title (${escaped(info.title)}) /Author (${escaped(info.author)}) >>`,
    ...pageObjects,
  ]
  let file = '%PDF-1.4\n'
  const offsets = objects.map((body, index) => {
    const offset = file.length
    file += `${index + 1} 0 obj\n${body}\nendobj\n`
    return offset
  })
  const start = file.length
  file += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  file += offsets.map((offset) => `${String(offset).padStart(10, '0')} 00000 n \n`).join('')
  file += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R /Info 4 0 R >>\nstartxref\n${start}\n%%EOF\n`
  return Buffer.from(file, 'latin1')
}

export function unknownPaper() {
  const title = `Citation Support in Held-Out Benchmarks ${crypto.randomUUID().slice(0, 8)}`
  const authors = ['Mira Okafor', 'Tomas Lindqvist']
  const year = 2021
  const abstractLines = ['We measure whether each sentence of a generated answer is supported', 'by the passage it cites, using a held-out benchmark of questions.']
  const body = (text: string): Line => ({ text, size: 11 })
  const buffer = pdf({ title, author: authors.join('; ') }, [
    [
      { text: title, size: 18 },
      body(`Copyright ${year} The Authors.`),
      body('Abstract'),
      ...abstractLines.map(body),
      body('1 Introduction'),
      body('Readers need to see which page supports each claim in an answer.'),
    ],
    [body('2 Results'), body('Citation support reached 91 percent on the held-out questions.')],
  ])
  return { title, authors, year, abstract: abstractLines.join(' '), buffer }
}
