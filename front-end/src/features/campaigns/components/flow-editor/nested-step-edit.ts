/**
 * Child step editors inside FlowEditor: overlay (nested dialog) vs standalone dialog.
 */

export const STEP_EDIT_OVERLAY_HOST_SELECTOR =
  '[data-slot="dialog-content"], [data-slot="sheet-content"]';

/** Keep a portaled child editor inside the parent modal's focus scope when possible. */
export function resolveStepEditOverlayHost(
  anchor: Pick<Element, 'closest'> | null,
  fallback: HTMLElement
): HTMLElement {
  return (
    (anchor?.closest(STEP_EDIT_OVERLAY_HOST_SELECTOR) as HTMLElement | null) ??
    fallback
  );
}

/** Use StepEditOverlay when FlowEditor sits in a parent dialog or compact list mode. */
export function shouldUseStepEditOverlay(
  nestedInDialog: boolean,
  compact: boolean
): boolean {
  return nestedInDialog || compact;
}

/** Standalone Radix Dialog for child edits (control-record full list mode). */
export function shouldUseChildStepDialog(
  nestedInDialog: boolean,
  compact: boolean
): boolean {
  return !nestedInDialog && !compact;
}

/** A parent scenario must not persist while a buffered child edit is uncommitted. */
export function canPersistScenario(childEditorOpen: boolean): boolean {
  return !childEditorOpen;
}
