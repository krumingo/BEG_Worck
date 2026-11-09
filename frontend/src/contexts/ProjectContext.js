import { createContext, useContext, useState, useCallback, useEffect } from "react";
import { CLEARED_EVENT } from "@/lib/pwa/clearLocalData";

const ProjectContext = createContext();

export function ProjectProvider({ children }) {
  const [activeProject, setActiveProjectState] = useState(null);

  const setActiveProject = useCallback((project) => {
    // project = { id, name, code, address_text } or null
    setActiveProjectState(project);
  }, []);

  const clearActiveProject = useCallback(() => {
    setActiveProjectState(null);
  }, []);

  // PWA-01: logout / tenant switch clears the in-memory active project too.
  useEffect(() => {
    window.addEventListener(CLEARED_EVENT, clearActiveProject);
    return () => window.removeEventListener(CLEARED_EVENT, clearActiveProject);
  }, [clearActiveProject]);

  return (
    <ProjectContext.Provider value={{ activeProject, setActiveProject, clearActiveProject }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useActiveProject() {
  return useContext(ProjectContext);
}
