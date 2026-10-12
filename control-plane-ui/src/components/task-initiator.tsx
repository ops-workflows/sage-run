export function TaskInitiator({ initiator }: { initiator: string | null }) {
  if (!initiator) return null;
  return (
    <div className="flex flex-wrap items-baseline gap-2 pt-1 text-xs text-[var(--color-text-tertiary)]">
      <span className="uppercase tracking-[0.15em]">Initiated By</span>
      <span className="min-w-0 break-all text-sm text-[var(--color-text-secondary)]">
        {initiator}
      </span>
    </div>
  );
}
