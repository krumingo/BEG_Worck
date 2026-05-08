import { createContext, useContext, useState, useCallback } from "react";

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

  return (
    <ProjectContext.Provider value={{ activeProject, setActiveProject, clearActiveProject }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useActiveProject() {
  return useContext(ProjectContext);
}
