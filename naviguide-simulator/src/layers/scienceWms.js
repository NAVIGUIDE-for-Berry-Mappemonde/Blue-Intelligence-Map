/** WMS EMODnet — mêmes couches que le mode Science de Blue Intelligence. */
export const SCIENCE_WMS_LAYERS = [
  {
    id: "bathymetry",
    url: "https://ows.emodnet-bathymetry.eu/wms",
    layers: "mean_multicolour",
    opacity: 0.5,
    pane: "science-wms-bathy",
    attribution: "EMODnet Bathymetry",
  },
  {
    id: "substrate",
    url: "https://drive.emodnet-geology.eu/geoserver/gtk/wms",
    layers: "seabed_substrate_1m",
    opacity: 0.75,
    pane: "science-wms-substrate",
    attribution: "EMODnet Geology",
  },
  {
    id: "cables",
    url: "https://ows.emodnet-humanactivities.eu/wms",
    layers: "telecablesactual,powercables",
    opacity: 1,
    pane: "science-wms-cables",
    attribution: "EMODnet Human Activities",
  },
];
