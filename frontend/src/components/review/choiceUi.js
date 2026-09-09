import { ExternalLink } from "lucide-react";

export function hostOf(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch (_) {
    return url || "";
  }
}

export function pathHint(url) {
  try {
    const leaf = decodeURIComponent(new URL(url).pathname).split("/").filter(Boolean).pop() || "";
    if (leaf.length < 3) return "";
    return leaf.length > 52 ? `${leaf.slice(0, 50)}…` : leaf;
  } catch (_) {
    return "";
  }
}

export function KeepDrop({ t, verdict, onKeep, onDrop, keepTestId, dropTestId }) {
  return (
    <div className="flex items-center gap-1 shrink-0">
      <button
        type="button"
        data-testid={keepTestId}
        aria-pressed={verdict === "keep"}
        onClick={onKeep}
        className={`px-1.5 py-0.5 font-mono text-[9px] border rounded-sm ${
          verdict === "keep"
            ? "border-bio/50 bg-bio/15 text-bio"
            : "border-line text-slate-400 hover:text-slate-200"
        }`}
      >
        {t("reviewKeep")}
      </button>
      <button
        type="button"
        data-testid={dropTestId}
        aria-pressed={verdict === "drop"}
        onClick={onDrop}
        className={`px-1.5 py-0.5 font-mono text-[9px] border rounded-sm ${
          verdict === "drop"
            ? "border-alert/50 bg-alert/10 text-alert"
            : "border-line text-slate-400 hover:text-slate-200"
        }`}
      >
        {t("reviewDrop")}
      </button>
    </div>
  );
}

export function UrlKeepRow({
  rec, t, selectable, kept, onToggle, keepTestId, testId, pathTestId, badge,
}) {
  const href = rec?.url || rec || "";
  return (
    <div className="flex items-center justify-between gap-2 min-w-0">
      {selectable ? (
        <label className="flex items-center gap-2 min-w-0 flex-1">
          <input
            type="checkbox"
            data-testid={keepTestId}
            checked={Boolean(kept)}
            onChange={onToggle}
            className="shrink-0 accent-accent"
          />
          <a
            href={href}
            target="_blank"
            rel="noreferrer"
            data-testid={testId}
            className="min-w-0 text-[11px] text-accent hover:text-white font-medium"
            title={href}
          >
            <span className="block truncate">{hostOf(href)}</span>
            {pathHint(href) ? (
              <span
                className="block font-mono text-[10px] text-slate-400 truncate"
                data-testid={pathTestId}
              >
                {pathHint(href)}
              </span>
            ) : null}
          </a>
        </label>
      ) : (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          data-testid={testId}
          className="min-w-0 text-[11px] text-accent hover:text-white font-medium"
          title={href}
        >
          <span className="block truncate">{hostOf(href)}</span>
          {pathHint(href) ? (
            <span className="block font-mono text-[10px] text-slate-400 truncate" data-testid={pathTestId}>
              {pathHint(href)}
            </span>
          ) : null}
        </a>
      )}
      <div className="flex items-center gap-1 shrink-0">
        {badge}
        <a href={href} target="_blank" rel="noreferrer" className="text-accent hover:text-white">
          <ExternalLink size={11} />
        </a>
      </div>
    </div>
  );
}

export function FicheShell({ testId, kindLabel, title, subtitle, extra, children }) {
  return (
    <section className="p-3 border-b border-line bg-raised/30 space-y-3" data-testid={testId}>
      <p className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">
        {kindLabel}
      </p>
      <div>
        <p className="font-heading text-sm text-white leading-snug">{title || "—"}</p>
        {subtitle ? (
          <p className="font-mono text-[10px] text-slate-500 mt-0.5">{subtitle}</p>
        ) : null}
        {extra}
      </div>
      {children}
    </section>
  );
}

export function FicheSection({ label, count, testId, children, empty }) {
  return (
    <div data-testid={testId}>
      <p className="font-mono text-[9px] uppercase tracking-[0.2em] text-slate-500 mb-1.5">
        {label}
        {count != null ? <span className="text-accent"> ({count})</span> : null}
      </p>
      {children || (
        <p className="text-[11px] text-slate-500 leading-relaxed">{empty}</p>
      )}
    </div>
  );
}
