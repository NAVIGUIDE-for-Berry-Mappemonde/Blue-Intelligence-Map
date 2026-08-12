/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useState, useEffect } from 'react';
import Sidebar from './components/Sidebar';
import ProjectMap from './components/Map';
import { projectsData as initialProjectsData } from './data/projects';

export default function App() {
  const [filters, setFilters] = useState({
    funder: 'All'
  });
  
  const [projects, setProjects] = useState(initialProjectsData);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchProjects = async () => {
      try {
        const response = await fetch('/api/projects');
        if (response.ok) {
          const data = await response.json();
          setProjects(data);
        }
      } catch (error) {
        console.error("Failed to fetch projects:", error);
      } finally {
        setIsLoading(false);
      }
    };
    
    fetchProjects();
  }, []);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-slate-950 font-sans">
      <Sidebar filters={filters} setFilters={setFilters} projects={projects} setProjects={setProjects} isLoading={isLoading} />
      <main className="flex-1 relative">
        <ProjectMap filters={filters} projects={projects} />
      </main>
    </div>
  );
}

