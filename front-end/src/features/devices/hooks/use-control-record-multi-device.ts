'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import type { Device } from '../types';
import { isManualControlEligible } from '../lib/control-record-device-state';
import {
  getActiveMultiSerials,
  getRenderSafeFollowerSerials,
  resetFollowersAfterPrimaryChange,
  sanitizeMultiFollowerSerials
} from '../lib/control-record-multi';

type UseControlRecordMultiDeviceArgs = {
  connectedDevices: Device[];
  selectedPrimarySerial: string | null;
  safeHierarchy: boolean;
  playerMode: boolean;
  maxFollowers: number;
};

export function useControlRecordMultiDevice({
  connectedDevices,
  selectedPrimarySerial,
  safeHierarchy,
  playerMode,
  maxFollowers
}: UseControlRecordMultiDeviceArgs) {
  const leftCollapsedBeforeMultiRef = useRef<boolean | null>(null);
  const previousPrimarySerialRef = useRef<string | null>(null);
  const prevMultiRef = useRef(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [multiFollowerSerials, setMultiFollowerSerials] = useState<string[]>(
    []
  );
  const [stepPickerOpen, setStepPickerOpen] = useState(true);

  const multiFollowerOptions = useMemo(
    () =>
      connectedDevices.filter(
        (d) => d.serial !== selectedPrimarySerial && isManualControlEligible(d)
      ),
    [connectedDevices, selectedPrimarySerial]
  );

  useEffect(() => {
    const allowed = multiFollowerOptions.map((d) => d.serial);
    setMultiFollowerSerials((prev) =>
      sanitizeMultiFollowerSerials(prev, allowed, maxFollowers)
    );
  }, [multiFollowerOptions, maxFollowers]);

  const renderSafeFollowerSerials = useMemo(
    () =>
      getRenderSafeFollowerSerials(
        previousPrimarySerialRef.current,
        selectedPrimarySerial,
        multiFollowerSerials
      ),
    [selectedPrimarySerial, multiFollowerSerials]
  );

  useEffect(() => {
    const nextPrimary = selectedPrimarySerial;
    const previousPrimary = previousPrimarySerialRef.current;
    setMultiFollowerSerials((prev) =>
      resetFollowersAfterPrimaryChange(previousPrimary, nextPrimary, prev)
    );
    previousPrimarySerialRef.current = nextPrimary;
  }, [selectedPrimarySerial]);

  const activeMultiSerials = useMemo(
    () =>
      getActiveMultiSerials(selectedPrimarySerial, renderSafeFollowerSerials),
    [selectedPrimarySerial, renderSafeFollowerSerials]
  );

  const selectedMultiFollowerDevices = useMemo(() => {
    const selected = new Set(renderSafeFollowerSerials);
    return connectedDevices.filter((d) => selected.has(d.serial));
  }, [connectedDevices, renderSafeFollowerSerials]);

  const hasMultiFollowers = renderSafeFollowerSerials.length > 0;
  const multiFocusMode = hasMultiFollowers && !stepPickerOpen && !playerMode;
  const showEditorPanel = !hasMultiFollowers || stepPickerOpen || playerMode;
  const treePanelOpen = safeHierarchy && !leftCollapsed && !hasMultiFollowers;

  useEffect(() => {
    if (hasMultiFollowers) {
      if (!prevMultiRef.current) {
        setStepPickerOpen(false);
      }
      setLeftCollapsed((prev) => {
        if (leftCollapsedBeforeMultiRef.current === null) {
          leftCollapsedBeforeMultiRef.current = prev;
        }
        return true;
      });
    } else {
      if (prevMultiRef.current) {
        setStepPickerOpen(true);
      }
      if (leftCollapsedBeforeMultiRef.current !== null) {
        const restore = leftCollapsedBeforeMultiRef.current;
        leftCollapsedBeforeMultiRef.current = null;
        setLeftCollapsed(restore);
      }
    }
    prevMultiRef.current = hasMultiFollowers;
  }, [hasMultiFollowers]);

  return {
    leftCollapsed,
    setLeftCollapsed,
    multiFollowerSerials,
    setMultiFollowerSerials,
    stepPickerOpen,
    setStepPickerOpen,
    multiFollowerOptions,
    renderSafeFollowerSerials,
    activeMultiSerials,
    selectedMultiFollowerDevices,
    hasMultiFollowers,
    multiFocusMode,
    showEditorPanel,
    treePanelOpen
  };
}
