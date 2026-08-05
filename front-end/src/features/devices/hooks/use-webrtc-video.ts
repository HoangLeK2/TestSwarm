import { useEffect, useMemo, useRef, useState, type RefObject } from 'react';
import {
  startWebRtcStream,
  type WebRtcStreamController
} from '../services/webrtc-stream';

type UseWebRtcVideoOptions = {
  enabled: boolean;
  restartKey?: number;
  control?: boolean;
  profile?: 'visible' | 'focused' | 'degraded';
  maxFps?: number;
  maxWidth?: number;
  bitrate?: number;
  onFrame?: () => void;
  onSize?: (width: number, height: number) => void;
  onError?: (error: unknown) => void;
};

const configuredCloseGraceMs = Number(
  process.env.NEXT_PUBLIC_WEBRTC_TRANSIENT_CLOSE_GRACE_MS ?? 2500
);
const WEBRTC_TRANSIENT_CLOSE_GRACE_MS = Number.isFinite(
  configuredCloseGraceMs
)
  ? Math.max(0, Math.min(15_000, Math.round(configuredCloseGraceMs)))
  : 2500;

type WarmWebRtcEntry = {
  controller: WebRtcStreamController;
  refs: number;
  closeTimer: ReturnType<typeof window.setTimeout> | null;
};

const warmWebRtcControllers = new Map<string, WarmWebRtcEntry>();

export function useWebRtcVideo(
  serial: string,
  videoRef: RefObject<HTMLVideoElement | null>,
  {
    enabled,
    restartKey = 0,
    control,
    profile,
    maxFps,
    maxWidth,
    bitrate,
    onFrame,
    onSize,
    onError
  }: UseWebRtcVideoOptions
) {
  const viewerId = useMemo(
    () => `webrtc-${Math.random().toString(36).slice(2)}-${Date.now()}`,
    []
  );
  const controllerRef = useRef<WebRtcStreamController | null>(null);
  const [active, setActive] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [failed, setFailed] = useState(false);
  const streamKey = useMemo(
    () =>
      [
        serial,
        control ? 'control' : 'view',
        profile ?? '',
        maxFps ?? '',
        maxWidth ?? '',
        bitrate ?? '',
        restartKey
      ].join('|'),
    [bitrate, control, maxFps, maxWidth, profile, restartKey, serial]
  );

  useEffect(() => {
    if (!enabled || !serial || !videoRef.current) {
      setActive(false);
      setConnecting(false);
      return;
    }

    const video = videoRef.current;
    const reused = acquireWarmController(streamKey);
    if (reused) {
      controllerRef.current = reused.controller;
      const detach = attachExistingController(
        reused.controller,
        video,
        () => {
          setActive(true);
          setConnecting(false);
          onFrame?.();
        },
        onSize
      );
      setFailed(false);
      setConnecting(false);
      setActive(true);
      return () => {
        detach();
        releaseWarmController(streamKey);
        controllerRef.current = null;
        setActive(false);
        setConnecting(false);
      };
    }

    const abort = new AbortController();
    setConnecting(true);
    setFailed(false);
    startWebRtcStream({
      serial,
      viewerId,
      video,
      signal: abort.signal,
      control,
      profile,
      maxFps,
      maxWidth,
      bitrate,
      onFrame: () => {
        setActive(true);
        setConnecting(false);
        onFrame?.();
      },
      onSize
    })
      .then((controller) => {
        if (abort.signal.aborted) {
          controller.close().catch(() => {});
          return;
        }
        controllerRef.current = controller;
        warmWebRtcControllers.set(streamKey, {
          controller,
          refs: 1,
          closeTimer: null
        });
      })
      .catch((error) => {
        if (abort.signal.aborted) return;
        setActive(false);
        setConnecting(false);
        setFailed(true);
        onError?.(error);
      });

    return () => {
      abort.abort();
      const controller = controllerRef.current;
      controllerRef.current = null;
      if (controller) {
        releaseWarmController(streamKey);
      }
      setActive(false);
      setConnecting(false);
    };
  }, [
    bitrate,
    control,
    enabled,
    maxFps,
    maxWidth,
    onError,
    onFrame,
    onSize,
    profile,
    restartKey,
    serial,
    streamKey,
    videoRef,
    viewerId
  ]);

  return { active, connecting, failed };
}

function acquireWarmController(key: string): WarmWebRtcEntry | null {
  const entry = warmWebRtcControllers.get(key);
  if (!entry) return null;
  if (entry.controller.peerConnection.connectionState === 'closed') {
    warmWebRtcControllers.delete(key);
    return null;
  }
  if (entry.closeTimer !== null) {
    window.clearTimeout(entry.closeTimer);
    entry.closeTimer = null;
  }
  entry.refs += 1;
  return entry;
}

function releaseWarmController(key: string) {
  const entry = warmWebRtcControllers.get(key);
  if (!entry) return;
  entry.refs = Math.max(0, entry.refs - 1);
  if (entry.refs > 0 || entry.closeTimer !== null) return;
  entry.closeTimer = window.setTimeout(() => {
    const current = warmWebRtcControllers.get(key);
    if (!current || current.refs > 0) return;
    warmWebRtcControllers.delete(key);
    current.controller.close().catch(() => {});
  }, WEBRTC_TRANSIENT_CLOSE_GRACE_MS);
}

function attachExistingController(
  controller: WebRtcStreamController,
  video: HTMLVideoElement,
  onFrame: () => void,
  onSize?: (width: number, height: number) => void
) {
  const track = controller.peerConnection
    .getReceivers()
    .map((receiver) => receiver.track)
    .find((candidate) => candidate?.kind === 'video');
  if (track && video.srcObject === null) {
    video.srcObject = new MediaStream([track]);
  }
  const markFrame = () => {
    onFrame();
    if (video.videoWidth && video.videoHeight) {
      onSize?.(video.videoWidth, video.videoHeight);
    }
  };
  video.addEventListener('loadeddata', markFrame);
  video.addEventListener('resize', markFrame);
  video.play().catch(() => {});
  if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
    markFrame();
  }
  return () => {
    video.removeEventListener('loadeddata', markFrame);
    video.removeEventListener('resize', markFrame);
    if (video.srcObject instanceof MediaStream) {
      video.srcObject = null;
    }
  };
}
