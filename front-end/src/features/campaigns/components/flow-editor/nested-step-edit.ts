/**
 * Child step editors inside FlowEditor: overlay (nested dialog) vs standalone dialog.
 */

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
