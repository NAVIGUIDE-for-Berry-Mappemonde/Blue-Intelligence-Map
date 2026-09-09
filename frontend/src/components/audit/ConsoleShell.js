import { useCallback, useEffect, useState } from "react";
import api from "../../api";
import CardShell from "./CardShell";
import RulesPanel from "./RulesPanel";
import RunsPanel from "./RunsPanel";
import JournalPanel from "./JournalPanel";
import AmpCard from "./AmpCard";
import FormalitiesCard from "./FormalitiesCard";
import MarinasCard from "./MarinasCard";
import CapitaineriesCard from "./CapitaineriesCard";
import ProjectsCard from "./ProjectsCard";
import { buildLaunchPayload, matchingProfile } from "../../lib/runRules";

const BORDER = {
  projects: "border-sonar/40",
  marinas: "border-alert/40",
  capitaineries: "border-accent/40",
  formalities: "border-amberx/40",
  amp: "border-[#4ade80]/40",
};

const TABS = [
  { id: "launch", key: "consoleTabLaunch" },
  { id: "rules", key: "consoleTabRules" },
  { id: "runs", key: "consoleTabRuns" },
  { id: "journal", key: "consoleTabJournal" },
];

export default function ConsoleShell({
  t, lang, mode, status, refresh, settings, onSettingsSaved, onPoeRefresh,
  showAnchorages, setShowAnchorages, anchoragesCount,
}) {
  const [tab, setTab] = useState("launch");
  const [catalog, setCatalog] = useState(null);
  const [values, setValues] = useState({});
  const [profile, setProfile] = useState("cdc_default");
  const [lastProfile, setLastProfile] = useState("cdc_default");
  const [errors, setErrors] = useState({});

  const applyCatalog = (data, { profileName }) => {
    setCatalog(data);
    setErrors({});
    const ov = data.profiles?.[profileName]?.overrides || {};
    const filled = {};
    (data.rules || []).forEach((r) => {
      filled[r.id] = ov[r.id] !== undefined ? ov[r.id] : r.value;
    });
    setValues(filled);
    const matched = matchingProfile(data, filled);
    setProfile(matched);
    if (matched) setLastProfile(matched);
  };

  const loadCatalog = useCallback(async (profileName, { pure } = {}) => {
    const params = { mode: mode || "projects" };
    if (profileName) params.profile = profileName;
    if (pure) params.from_settings = false;
    const { data } = await api.get("/run-rules", { params });
    return data;
  }, [mode]);

  useEffect(() => {
    let alive = true;
    setCatalog(null);
    setValues({});
    setProfile("cdc_default");
    setLastProfile("cdc_default");
    setErrors({});
    (async () => {
      try {
        const data = await loadCatalog("cdc_default", { pure: true });
        if (alive) applyCatalog(data, { profileName: "cdc_default" });
      } catch (_) { /* transient */ }
    })();
    return () => { alive = false; };
  }, [loadCatalog]);

  const onSelectProfile = async (name, opts = {}) => {
    if (!name) {
      setProfile(null);
      return;
    }
    if (opts.keepLast) {
      setProfile(name);
      if (name) setLastProfile(name);
      return;
    }
    try {
      const data = await loadCatalog(name, { pure: true });
      applyCatalog(data, { profileName: name });
      setProfile(name);
      setLastProfile(name);
      setErrors({});
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    }
  };

  const rulesPayload = () => buildLaunchPayload(
    catalog || { rules: [], profiles: {} },
    lastProfile || "cdc_default",
    values,
    settings,
  );

  const reuseRules = ({ profile: p, values: v }) => {
    setValues((prev) => ({ ...prev, ...v }));
    setLastProfile(p || "cdc_default");
    setProfile(null);
    setTab("rules");
  };

  const saveDefaults = async (body) => {
    await api.put("/settings", body);
    onSettingsSaved && onSettingsSaved();
  };

  const launch = (
    mode === "marinas" ? (
      <MarinasCard t={t} showAnchorages={showAnchorages} setShowAnchorages={setShowAnchorages}
        anchoragesCount={anchoragesCount} rulesPayload={rulesPayload} />
    ) : mode === "capitaineries" ? (
      <CapitaineriesCard t={t} rulesPayload={rulesPayload} />
    ) : mode === "formalities" ? (
      <FormalitiesCard t={t} onPoeRefresh={onPoeRefresh} rulesPayload={rulesPayload} />
    ) : mode === "amp" ? (
      <AmpCard t={t} rulesPayload={rulesPayload} />
    ) : (
      <ProjectsCard t={t} status={status} refresh={refresh} rulesPayload={rulesPayload} />
    )
  );

  return (
    <div data-testid="audit-batch-hub" data-mode-card={mode || "projects"}>
      <CardShell borderCls={BORDER[mode] || BORDER.projects}>
        <div className="flex border border-line rounded-sm overflow-hidden" data-testid="console-tabs">
          {TABS.map((tabDef, i) => (
            <button
              key={tabDef.id}
              type="button"
              data-testid={`console-tab-${tabDef.id}`}
              onClick={() => setTab(tabDef.id)}
              className={`flex-1 py-1.5 font-mono text-[10px] uppercase tracking-[0.16em] ${
                i ? "border-l border-line" : ""
              } ${tab === tabDef.id ? "bg-accent/15 text-accent" : "text-slate-400 hover:bg-raised hover:text-slate-200"}`}
            >
              {t(tabDef.key)}
            </button>
          ))}
        </div>

        <div className={tab === "launch" ? "" : "hidden"}>{launch}</div>
        <div className={tab === "rules" ? "" : "hidden"}>
          {!catalog && (
            <p className="font-mono text-[10px] text-slate-500" data-testid="rules-loading">…</p>
          )}
          {catalog && (
            <RulesPanel
              t={t} lang={lang} mode={mode} catalog={catalog}
              values={values} setValues={setValues}
              profile={profile} lastProfile={lastProfile}
              onSelectProfile={onSelectProfile}
              errors={errors} setErrors={setErrors}
              onSaveDefaults={saveDefaults}
            />
          )}
        </div>
        <div className={tab === "runs" ? "" : "hidden"}>
          <RunsPanel t={t} lang={lang} mode={mode} catalog={catalog} onReuse={reuseRules} />
        </div>
        <div className={tab === "journal" ? "" : "hidden"}>
          <JournalPanel t={t} mode={mode} status={status} />
        </div>
      </CardShell>
    </div>
  );
}
