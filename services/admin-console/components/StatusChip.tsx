// A ticket's lifecycle status: a coloured dot and its name.

export default function StatusChip({ name, color }: { name: string; color?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-[13px]">
      <span
        aria-hidden
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ background: color || "var(--border-strong)" }}
      />
      {name}
    </span>
  );
}
