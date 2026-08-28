/** Card shell — enveloppe commune des cartes du Swarm Intelligence Hub. */
export default function CardShell({ title, icon, borderCls, children }) {
  // Header row only when a title is provided — the mode name is already
  // visible in the top nav + left sidebar, no need to repeat it here.
  return (
    <div className={`border bg-surface flex flex-col ${borderCls}`}>
      {title && (
        <div className="px-4 py-2.5 border-b border-line flex items-center gap-2">
          {icon}
          <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-400">{title}</p>
        </div>
      )}
      <div className="p-4 space-y-3 flex-1">{children}</div>
    </div>
  );
}

export const smallInput = "w-full bg-raised border border-line rounded-sm px-2 py-1.5 text-xs text-slate-200 focus:outline-none focus:ring-2 focus:ring-accent/50";
