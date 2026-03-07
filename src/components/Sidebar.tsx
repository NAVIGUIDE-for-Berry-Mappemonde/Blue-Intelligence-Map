import { Filter, Map as MapIcon, Layers, Info, Download, Loader2 } from 'lucide-react';

interface SidebarProps {
  filters: {
    funder: string;
  };
  setFilters: (filters: any) => void;
  projects: any;
  setProjects: (projects: any) => void;
  isLoading: boolean;
}

export default function Sidebar({ filters, setFilters, projects, isLoading }: SidebarProps) {
  const funders = ['All', ...Array.from(new Set(projects.features.map((f: any) => f.properties.funder).filter(Boolean)))].sort();

  const funderCounts = projects.features.reduce((acc: any, feature: any) => {
    const funder = feature.properties.funder;
    if (funder) {
      acc[funder] = (acc[funder] || 0) + 1;
    }
    return acc;
  }, {});
  
  const totalCount = projects.features.length;

  const handleDownload = () => {
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(projects, null, 2));
    const downloadAnchorNode = document.createElement('a');
    downloadAnchorNode.setAttribute("href", dataStr);
    downloadAnchorNode.setAttribute("download", "blue_intelligence_projects.geojson");
    document.body.appendChild(downloadAnchorNode);
    downloadAnchorNode.click();
    downloadAnchorNode.remove();
  };

  return (
    <div className="w-80 bg-slate-900 border-r border-slate-800 flex flex-col h-full text-slate-200 overflow-y-auto">
      <div className="p-6 border-b border-slate-800">
        <div className="flex items-center gap-3 mb-2">
          <div className="p-2 bg-blue-500/20 text-blue-400 rounded-lg">
            <MapIcon size={24} />
          </div>
          <h1 className="text-xl font-bold text-white tracking-tight">Blue Intelligence</h1>
        </div>
        <p className="text-xs text-slate-400 leading-relaxed">
          Interactive database and visualization of marine conservation projects globally.
        </p>
      </div>

      <div className="p-6 flex-1">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-slate-300 uppercase tracking-wider">
            <Filter size={16} />
            <span>Map Filters</span>
          </div>
          {isLoading && (
            <div className="flex items-center gap-2 text-xs text-blue-400">
              <Loader2 size={12} className="animate-spin" />
              <span>Loading Data...</span>
            </div>
          )}
        </div>

        <div className="space-y-6">
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-2">
              Funder / Organization
            </label>
            <select
              value={filters.funder}
              onChange={(e) => setFilters({ ...filters, funder: e.target.value })}
              className="w-full bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="All">All ({totalCount})</option>
              {funders.filter(f => f !== 'All').map((funder: any) => (
                <option key={funder} value={funder}>
                  {funder} ({funderCounts[funder]})
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="mt-8 space-y-3">
          <button
            onClick={handleDownload}
            className="w-full flex items-center justify-center gap-2 bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors"
          >
            <Download size={16} />
            <span>Download GeoJSON</span>
          </button>
        </div>

        <div className="mt-8">
          <div className="flex items-center gap-2 mb-4 text-sm font-semibold text-slate-300 uppercase tracking-wider">
            <Layers size={16} />
            <span>Map Legend</span>
          </div>
          <div className="space-y-3">
            <div className="flex items-center gap-3">
              <div className="w-4 h-4 rounded-full bg-sky-400 border-2 border-white"></div>
              <span className="text-sm text-slate-400">Individual Project</span>
            </div>
            <div className="flex items-center gap-3">
              <div className="w-6 h-6 rounded-full bg-blue-500 border-2 border-white flex items-center justify-center">
                <span className="text-[10px] font-bold text-white">5</span>
              </div>
              <span className="text-sm text-slate-400">Project Cluster</span>
            </div>
          </div>
        </div>
      </div>

      <div className="p-6 border-t border-slate-800 bg-slate-900/50">
        <div className="flex gap-3 items-start">
          <Info size={16} className="text-slate-500 shrink-0 mt-0.5" />
          <p className="text-xs text-slate-500 leading-relaxed">
            Data sourced directly from curated marine conservation foundations. No simulated or mock data is used.
          </p>
        </div>
      </div>
    </div>
  );
}
