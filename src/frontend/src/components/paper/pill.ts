/**
 * A paper mention pill, in the composer and in sent questions (ARA-096): quiet surface, small radius and label size,
 * like the citation chips it sits beside. It never wraps inside itself, and a long label truncates within the line.
 */
export const pillClass = 'mx-px inline-flex max-w-[min(100%,18rem)] items-baseline gap-1 rounded-sm bg-muted px-1.5 align-baseline text-xs leading-5 font-medium whitespace-nowrap text-foreground'
export const pillIconClass = 'size-3 shrink-0 self-center text-muted-foreground'
export const pillLabelClass = 'min-w-0 truncate'
