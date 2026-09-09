import BatchHub from "./BatchHub";

export default function AuditView({
  t, lang, mode, status, refresh, onPoeRefresh, settings, onSettingsSaved,
  showAnchorages, setShowAnchorages, anchoragesCount,
}) {
  return (
    <div className="h-full overflow-y-auto p-5 space-y-5 bi-audit-themed" data-testid="audit-view">
      <div className="flex items-center justify-between">
        <h2 className="font-heading font-black text-xl text-accent">{t("auditTitle")}</h2>
        <span className="font-mono text-[10px] uppercase tracking-[0.2em] text-slate-500">
          {t("mode" + (mode || "projects").charAt(0).toUpperCase() + (mode || "projects").slice(1))}
        </span>
      </div>
      <BatchHub
        t={t}
        lang={lang}
        mode={mode}
        status={status}
        refresh={refresh}
        settings={settings}
        onSettingsSaved={onSettingsSaved}
        onPoeRefresh={onPoeRefresh}
        showAnchorages={showAnchorages}
        setShowAnchorages={setShowAnchorages}
        anchoragesCount={anchoragesCount}
      />
    </div>
  );
}
