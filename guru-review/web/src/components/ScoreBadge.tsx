interface Props {
  score: 0 | 1 | 2 | 3;
}

const COLORS: Record<0 | 1 | 2 | 3, string> = {
  3: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
  2: 'bg-blue-500/20 text-blue-300 border-blue-500/40',
  1: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  0: 'bg-rose-500/20 text-rose-300 border-rose-500/40',
};

export function ScoreBadge({ score }: Props): React.ReactElement {
  return (
    <span
      className={`inline-flex h-5 min-w-[1.5rem] items-center justify-center rounded border px-1.5 mono text-xs ${COLORS[score]}`}
      aria-label={`score ${score} of 3`}
    >
      {score}
    </span>
  );
}
