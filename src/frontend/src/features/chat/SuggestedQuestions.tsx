import { Button } from '@/components/ui/button'

// The example questions from the homework brief (hw1.md, "Ask Questions About a Paper").
const questions = [
  'What problem does this paper address?',
  'What is the main idea of the proposed approach?',
  'What datasets are used?',
  'What are the major limitations?',
  'How does this method compare with the baselines?',
]

export function SuggestedQuestions({ onSelect, disabled }: { onSelect: (question: string) => void; disabled?: boolean }) {
  return (
    <div role="group" aria-label="Suggested questions" className="grid gap-2.5">
      <p className="text-sm text-muted-foreground">Start with a question</p>
      <div className="flex flex-wrap gap-2">
        {questions.map((question) => (
          <Button key={question} type="button" variant="outline" size="sm" disabled={disabled} onClick={() => onSelect(question)} className="h-auto min-h-8 rounded-full px-3 py-1.5 text-left font-normal whitespace-normal text-muted-foreground hover:text-foreground">
            {question}
          </Button>
        ))}
      </div>
    </div>
  )
}
