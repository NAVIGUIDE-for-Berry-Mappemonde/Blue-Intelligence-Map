import FormalitiesCard from "./audit/FormalitiesCard";
import MarinasCard from "./audit/MarinasCard";
import CapitaineriesCard from "./audit/CapitaineriesCard";
import ProjectsCard from "./audit/ProjectsCard";

/**
 * BatchHub — bloc contextuel de la vue Audit.
 *
 * Affiche UNIQUEMENT la carte du mode actif (projects / marinas / formalities),
 * chacune vivant dans son propre fichier sous components/audit/. Le polling de
 * chaque carte ne tourne que lorsqu'elle est montée (= mode actif).
 */
export default function BatchHub({ t, mode, status, refresh, settings, onSettingsSaved, onPoeRefresh, showAnchorages, setShowAnchorages, anchoragesCount }) {
  if (mode === "marinas") {
    return (
      <MarinasCard
        t={t}
        showAnchorages={showAnchorages}
        setShowAnchorages={setShowAnchorages}
        anchoragesCount={anchoragesCount}
      />
    );
  }
  if (mode === "capitaineries") {
    return <CapitaineriesCard t={t} />;
  }
  if (mode === "formalities") {
    return <FormalitiesCard t={t} onPoeRefresh={onPoeRefresh} />;
  }
  return (
    <ProjectsCard
      t={t}
      status={status}
      refresh={refresh}
      settings={settings}
      onSettingsSaved={onSettingsSaved}
    />
  );
}
