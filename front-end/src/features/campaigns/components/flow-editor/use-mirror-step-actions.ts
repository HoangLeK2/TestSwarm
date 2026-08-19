'use client';

/**
 * Edit a step from the device mirror while its editor panel is open.
 *
 * The editors buffer edits in a ref and only write them into the tree when the
 * panel closes, so these actions cannot just close the panel and let the (now
 * unmounted) fields apply the result — the write would land in a ref nobody
 * reads again. Resolve the target up front, close, then apply directly.
 *
 * Closing is the point: the panel is a modal over the device mirror, and both
 * actions are a drag on that mirror. Same reason selector/coordinate picking
 * closes the panel before handing control back to the phone view.
 */
import { useMemo, useRef } from 'react';

import type { FlowStep } from '../scenario-steps/types';
import { useImageTemplateScenario } from './image-template-scenario';

export type CropTarget = {
  /** Latest value of the step, buffered edits included. */
  step: FlowStep;
  /** Writes the patched step into the tree; must not read panel state. */
  apply: (next: FlowStep) => void;
};

export type MirrorStepActions = {
  /** Cut a tap_image template out of the screen. */
  cropImage?: () => Promise<null>;
  /** Bound an OCR read to one area of the screen. */
  pickRegion?: () => Promise<null>;
};

export function useMirrorStepActions(
  resolveTarget: () => CropTarget | null,
  close: () => void
): MirrorStepActions {
  const { requestCropImage, requestRegion } = useImageTemplateScenario();
  const latest = useRef({ resolveTarget, close });
  latest.current = { resolveTarget, close };

  return useMemo(() => {
    /** Close the panel, run the mirror interaction, patch the step. */
    const fromMirror = <T>(
      run: () => Promise<T | null>,
      patch: (step: FlowStep, value: T) => FlowStep
    ) => {
      return async () => {
        // Resolve before closing: afterwards the selection state is gone.
        const target = latest.current.resolveTarget();
        latest.current.close();
        const value = await run();
        if (value == null || !target) return null;
        target.apply(patch(target.step, value));
        return null;
      };
    };

    return {
      cropImage: requestCropImage
        ? fromMirror(requestCropImage, (step, pick) => ({
            ...step,
            template_key: pick.templateKey,
            template_screen_w: pick.screenW,
            template_screen_h: pick.screenH
          }))
        : undefined,
      pickRegion: requestRegion
        ? fromMirror(requestRegion, (step, region) => ({ ...step, region }))
        : undefined
    };
  }, [requestCropImage, requestRegion]);
}
