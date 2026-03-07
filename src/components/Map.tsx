import { useMemo, useState } from 'react';
import Map, { Source, Layer, Popup, NavigationControl } from 'react-map-gl/maplibre';
import 'maplibre-gl/dist/maplibre-gl.css';

interface ProjectMapProps {
  filters: {
    funder: string;
  };
  projects: any;
}

export default function ProjectMap({ filters, projects }: ProjectMapProps) {
  const [hoverInfo, setHoverInfo] = useState<any>(null);

  const data = useMemo(() => {
    const filteredFeatures = projects.features.filter((feature: any) => {
      const matchFunder = filters.funder === 'All' || feature.properties.funder === filters.funder;
      return matchFunder;
    });
    return { ...projects, features: filteredFeatures };
  }, [filters, projects]);

  return (
    <div className="w-full h-full relative">
      <Map
        initialViewState={{
          longitude: 0,
          latitude: 20,
          zoom: 1.5
        }}
        mapStyle="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
        interactiveLayerIds={['unclustered-point']}
        onClick={(e) => {
          if (e.features && e.features.length > 0) {
            setHoverInfo({
              longitude: e.lngLat.lng,
              latitude: e.lngLat.lat,
              feature: e.features[0]
            });
          } else {
            setHoverInfo(null);
          }
        }}
        onMouseEnter={(e) => {
          const map = e?.target;
          if (map) map.getCanvas().style.cursor = 'pointer';
        }}
        onMouseLeave={(e) => {
          const map = e?.target;
          if (map) map.getCanvas().style.cursor = '';
        }}
        cursor={hoverInfo ? 'pointer' : 'grab'}
      >
        <NavigationControl position="top-right" />
        
        <Source
          id="projects"
          type="geojson"
          data={data}
          cluster={true}
          clusterMaxZoom={14}
          clusterRadius={50}
        >
          <Layer
            id="clusters"
            type="circle"
            source="projects"
            filter={['has', 'point_count']}
            paint={{
              'circle-color': [
                'step',
                ['get', 'point_count'],
                '#0ea5e9', // Blue for small clusters
                5,
                '#3b82f6', // Darker blue for medium
                10,
                '#2563eb'  // Even darker for large
              ],
              'circle-radius': [
                'step',
                ['get', 'point_count'],
                15,
                5,
                20,
                10,
                25
              ],
              'circle-stroke-width': 2,
              'circle-stroke-color': '#ffffff'
            }}
          />
          
          <Layer
            id="cluster-count"
            type="symbol"
            source="projects"
            filter={['has', 'point_count']}
            layout={{
              'text-field': '{point_count_abbreviated}',
              'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'],
              'text-size': 12
            }}
            paint={{
              'text-color': '#ffffff'
            }}
          />

          <Layer
            id="unclustered-point"
            type="circle"
            source="projects"
            filter={['!', ['has', 'point_count']]}
            paint={{
              'circle-color': '#38bdf8',
              'circle-radius': 8,
              'circle-stroke-width': 2,
              'circle-stroke-color': '#ffffff'
            }}
          />
        </Source>

        {hoverInfo && (
          <Popup
            longitude={hoverInfo.longitude}
            latitude={hoverInfo.latitude}
            closeButton={true}
            closeOnClick={false}
            onClose={() => setHoverInfo(null)}
            className="z-50"
            anchor="bottom"
            offset={15}
            maxWidth="300px"
          >
            <div className="p-1 text-slate-800">
              {hoverInfo.feature.properties.image && (
                <img 
                  src={hoverInfo.feature.properties.image} 
                  alt={hoverInfo.feature.properties.title} 
                  className="w-full h-32 object-cover rounded-md mb-2"
                  referrerPolicy="no-referrer"
                />
              )}
              <h3 className="font-bold text-sm mb-1">{hoverInfo.feature.properties.title}</h3>
              <p className="text-xs text-slate-600 mb-2 font-medium">{hoverInfo.feature.properties.funder}</p>
              <p className="text-xs mb-2 line-clamp-3">{hoverInfo.feature.properties.description}</p>
              <a 
                href={hoverInfo.feature.properties.url} 
                target="_blank" 
                rel="noreferrer"
                className="text-xs text-blue-600 hover:underline font-medium"
              >
                View Project &rarr;
              </a>
            </div>
          </Popup>
        )}
      </Map>
    </div>
  );
}
