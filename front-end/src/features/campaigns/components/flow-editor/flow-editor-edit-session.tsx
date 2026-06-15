'use client';

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  type ReactNode
} from 'react';

type FlowEditorEditSession = {
  setChildEditorOpen: (open: boolean) => void;
};

const FlowEditorEditSessionContext =
  createContext<FlowEditorEditSession | null>(null);

export function FlowEditorEditSessionProvider({
  onChildStepEditorOpenChange,
  children
}: {
  onChildStepEditorOpenChange?: (open: boolean) => void;
  children: ReactNode;
}) {
  const openCountRef = useRef(0);
  const setChildEditorOpen = useCallback(
    (open: boolean) => {
      openCountRef.current = Math.max(0, openCountRef.current + (open ? 1 : -1));
      onChildStepEditorOpenChange?.(openCountRef.current > 0);
    },
    [onChildStepEditorOpenChange]
  );
  const value = useMemo(
    () => ({ setChildEditorOpen }),
    [setChildEditorOpen]
  );
  if (!onChildStepEditorOpenChange) return children;
  return (
    <FlowEditorEditSessionContext.Provider value={value}>
      {children}
    </FlowEditorEditSessionContext.Provider>
  );
}

export function useFlowEditorEditSession(): FlowEditorEditSession | null {
  return useContext(FlowEditorEditSessionContext);
}
