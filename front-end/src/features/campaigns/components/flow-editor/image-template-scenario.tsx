'use client';

/**
 * Which scenario owns the image templates of the steps being edited.
 *
 * Templates live in object storage under a per-scenario prefix, so both reading
 * one back (presigned URL) and uploading a new one need the scenario id. The
 * step editor is reached through several nesting paths — FlowEditor, bracket
 * children, the campaign scenario dialog, the device control view — and the id
 * is only known at the outermost of those, so a context beats threading an
 * optional prop through every level in between.
 *
 * Absent provider means "no scenario yet" (e.g. the reusable-template editors):
 * the tap_image fields then hide the image and the crop button instead of
 * calling an endpoint that would 404.
 */
import { createContext, useContext, useEffect, useMemo, useState } from 'react';

import { orgScenariosApi } from '@/features/org-scenarios/services/api';

export type ImageTemplatePickResult = {
  templateKey: string;
  screenW?: number;
  screenH?: number;
  preview: string;
  warning: string;
};

/** Normalised 0–1 rectangle in device screen space. */
export type MirrorRegion = { x1: number; y1: number; x2: number; y2: number };

type ImageTemplateScenario = {
  scenarioId: string | null;
  /**
   * Crop from the live device mirror, when the surrounding screen has one.
   * Rides in the context rather than as a prop because the step-list editor
   * reaches the fields through FlowEditor → VirtualizedFlowEditor →
   * BracketBlock, none of which carry crop concerns.
   */
  requestCropImage?: () => Promise<ImageTemplatePickResult | null>;
  /**
   * Same drag on the mirror, but the caller keeps the rectangle instead of
   * turning it into a stored image — used to bound an OCR read to one area.
   */
  requestRegion?: () => Promise<MirrorRegion | null>;
};

const ImageTemplateScenarioContext = createContext<ImageTemplateScenario>({
  scenarioId: null
});

export function ImageTemplateScenarioProvider({
  scenarioId,
  requestCropImage,
  requestRegion,
  children
}: {
  scenarioId: string | null | undefined;
  requestCropImage?: () => Promise<ImageTemplatePickResult | null>;
  requestRegion?: () => Promise<MirrorRegion | null>;
  children: React.ReactNode;
}) {
  const value = useMemo(
    () => ({ scenarioId: scenarioId ?? null, requestCropImage, requestRegion }),
    [scenarioId, requestCropImage, requestRegion]
  );
  return (
    <ImageTemplateScenarioContext.Provider value={value}>
      {children}
    </ImageTemplateScenarioContext.Provider>
  );
}

export function useImageTemplateScenario(): ImageTemplateScenario {
  return useContext(ImageTemplateScenarioContext);
}

export function useImageTemplateScenarioId(): string | null {
  return useContext(ImageTemplateScenarioContext).scenarioId;
}

/**
 * Presigned URL for a stored template, cached across components.
 *
 * A flow with a dozen tap_image steps renders a dozen cards plus the open
 * detail panel, and every remount would otherwise presign the same object
 * again. The backend signs for an hour; expiring the cache well before that
 * keeps a long editing session from ever showing a dead URL.
 */
const PRESIGN_TTL_MS = 45 * 60 * 1000;
const urlCache = new Map<string, { url: string; at: number }>();
const inFlight = new Map<string, Promise<string>>();

function presign(scenarioId: string, key: string): Promise<string> {
  const id = `${scenarioId}|${key}`;
  const hit = urlCache.get(id);
  if (hit && Date.now() - hit.at < PRESIGN_TTL_MS)
    return Promise.resolve(hit.url);
  const pending = inFlight.get(id);
  if (pending) return pending;
  const req = orgScenariosApi
    .getImageTemplateUrl(scenarioId, key)
    .then((url) => {
      urlCache.set(id, { url, at: Date.now() });
      return url;
    })
    .finally(() => {
      inFlight.delete(id);
    });
  inFlight.set(id, req);
  return req;
}

/** Drop a cached URL after the browser reports it unusable (expired/deleted). */
export function forgetImageTemplateUrl(scenarioId: string, key: string) {
  urlCache.delete(`${scenarioId}|${key}`);
}

export function useImageTemplateUrl(templateKey: string | undefined): {
  url: string;
  failed: boolean;
  forget: () => void;
} {
  const scenarioId = useImageTemplateScenarioId();
  const [url, setUrl] = useState('');
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!templateKey || !scenarioId) {
      setUrl('');
      setFailed(false);
      return;
    }
    let cancelled = false;
    setFailed(false);
    presign(scenarioId, templateKey)
      .then((next) => {
        if (!cancelled) setUrl(next);
      })
      .catch(() => {
        if (cancelled) return;
        setUrl('');
        setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [templateKey, scenarioId]);

  return {
    url,
    failed,
    forget: () => {
      if (scenarioId && templateKey)
        forgetImageTemplateUrl(scenarioId, templateKey);
      setUrl('');
      setFailed(true);
    }
  };
}
