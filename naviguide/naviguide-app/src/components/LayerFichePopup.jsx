import { Popup } from "react-map-gl/maplibre";
import { X } from "lucide-react";

function hostLabel(url) {
  try {
    return String(url).replace(/^https?:\/\//, "").replace(/\/$/, "").slice(0, 48);
  } catch {
    return String(url || "").slice(0, 48);
  }
}

function Row({ label, children }) {
  if (!children) return null;
  return (
    <div className="muted" style={{ marginTop: 6 }}>
      {label ? <div style={{ fontSize: 9, textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 2 }}>{label}</div> : null}
      {children}
    </div>
  );
}

export function LayerFichePopup({ popup, onClose }) {
  if (!popup) return null;
  const { lon, lat, kind, props = {} } = popup;

  let title = props.name || props.title || props.GEONAME || props.geoname || props.portName || "—";
  let subtitle = "";
  let extra = null;

  if (kind === "zee") {
    title = props.GEONAME || props.geoname || props.name || "ZEE";
    subtitle = [props.TERRITORY1 || props.territory1, props.POL_TYPE || props.pol_type, props.ISO_TER1]
      .filter(Boolean).join(" · ");
  } else if (kind === "marina") {
    subtitle = props.country || "";
    extra = (
      <>
        <Row label="Site">{props.website ? <a href={props.website} target="_blank" rel="noreferrer">{hostLabel(props.website)}</a> : null}</Row>
        <Row>{props.telephone}</Row>
      </>
    );
  } else if (kind === "project") {
    title = props.title || props.name || "Projet";
    subtitle = [props.funder, props.category_group].filter(Boolean).join(" · ");
    extra = (
      <>
        {props.description ? <p className="muted" style={{ margin: "6px 0" }}>{props.description}</p> : null}
        {props.url ? <a href={props.url} target="_blank" rel="noreferrer">Voir le projet →</a> : null}
      </>
    );
  } else if (kind === "capitainerie") {
    extra = (
      <>
        <Row label="Téléphone">{props.telephone ? <a href={`tel:${props.telephone}`}>{props.telephone}</a> : null}</Row>
        <Row label="VHF">{props.canal_vhf}</Row>
        <Row label="Site">{props.website ? <a href={props.website} target="_blank" rel="noreferrer">{hostLabel(props.website)}</a> : null}</Row>
      </>
    );
  } else if (kind === "poe") {
    title = props.name || "Port d'entrée";
    subtitle = [props.country, props.spatial_kind].filter(Boolean).join(" · ");
    extra = props.source_urls?.[0]
      ? <a href={props.source_urls[0]} target="_blank" rel="noreferrer">{hostLabel(props.source_urls[0])}</a>
      : null;
  } else if (kind === "amp") {
    title = props.name || props.site_id || "AMP";
    subtitle = [props.designation, props.country].filter(Boolean).join(" · ");
    extra = (
      <>
        {props.lfp != null ? <div className="muted" style={{ marginTop: 6 }}>LFP {props.lfp}</div> : null}
        {props.managing_authority ? <div className="muted">{props.managing_authority}</div> : null}
        {props.manager_url ? <Row label="Gestionnaire"><a href={props.manager_url} target="_blank" rel="noreferrer">{hostLabel(props.manager_url)}</a></Row> : null}
        {props.visit_url ? <Row label="Visite"><a href={props.visit_url} target="_blank" rel="noreferrer">{hostLabel(props.visit_url)}</a></Row> : null}
      </>
    );
  } else if (kind === "port") {
    subtitle = [props.country, props.region].filter(Boolean).join(" · ");
  }

  return (
    <Popup
      longitude={lon}
      latitude={lat}
      anchor="bottom"
      onClose={onClose}
      closeButton={false}
      className="!bg-transparent !border-none !shadow-none custom-popup"
    >
      <div className="layer-fiche-popup" data-testid={`fiche-${kind}`}>
        <button
          type="button"
          onClick={onClose}
          style={{ position: "absolute", top: 8, right: 8, color: "#94a3b8", background: "none", border: 0, cursor: "pointer" }}
        >
          <X size={12} />
        </button>
        <h3>{title}</h3>
        {subtitle ? <div className="muted">{subtitle}</div> : null}
        {extra}
      </div>
    </Popup>
  );
}

