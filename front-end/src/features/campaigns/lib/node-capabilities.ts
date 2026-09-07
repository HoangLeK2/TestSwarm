export type NodeRisk = 'low' | 'medium' | 'high';

export type NodeCapability = {
  type: string;
  group: 'action' | 'control' | 'variable';
  risk: NodeRisk;
  requires: string[];
  surfaces: string[];
  recorder_evidence: string[];
  inspector_hints: string[];
  description?: string;
};

export type NodeCapabilityRegistry = Record<string, NodeCapability>;

export type DeviceCapabilityMap = Record<string, unknown>;

export type NodeCapabilityStatus = {
  type: string;
  risk: NodeRisk;
  required: string[];
  missing: string[];
  unknown: string[];
  ok: boolean;
};

export type NodeCapabilityReadinessKind =
  | 'ready'
  | 'missing'
  | 'unknown'
  | 'none';

export type NodeCapabilityReadiness = {
  kind: NodeCapabilityReadinessKind;
  risk: NodeRisk;
  required: string[];
  missing: string[];
  unknown: string[];
};

export function evaluateNodeCapabilityStatus(
  capability: NodeCapability,
  deviceCapabilities: DeviceCapabilityMap | null | undefined
): NodeCapabilityStatus {
  const caps = deviceCapabilities ?? {};
  const required = capability.requires ?? [];
  const missing: string[] = [];
  const unknown: string[] = [];

  for (const key of required) {
    if (!(key in caps)) {
      unknown.push(key);
      continue;
    }
    if (!Boolean(caps[key])) {
      missing.push(key);
    }
  }

  return {
    type: capability.type,
    risk: capability.risk,
    required,
    missing,
    unknown,
    ok: missing.length === 0
  };
}

export function nodeCapabilityBadgeLabel(status: NodeCapabilityStatus): string {
  if (status.missing.length > 0) {
    return `missing ${status.missing.join(', ')}`;
  }
  if (status.unknown.length > 0) {
    return `unknown ${status.unknown.join(', ')}`;
  }
  if (status.required.length === 0) {
    return status.risk;
  }
  return `${status.risk} · ${status.required.join(', ')}`;
}

export function nodeCapabilityReadiness(
  capability: NodeCapability,
  deviceCapabilities: DeviceCapabilityMap | null | undefined
): NodeCapabilityReadiness {
  const status = evaluateNodeCapabilityStatus(capability, deviceCapabilities);
  if (status.missing.length > 0) {
    return {
      kind: 'missing',
      risk: status.risk,
      required: status.required,
      missing: status.missing,
      unknown: status.unknown
    };
  }
  if (status.unknown.length > 0) {
    return {
      kind: 'unknown',
      risk: status.risk,
      required: status.required,
      missing: status.missing,
      unknown: status.unknown
    };
  }
  if (status.required.length === 0) {
    return {
      kind: 'none',
      risk: status.risk,
      required: status.required,
      missing: status.missing,
      unknown: status.unknown
    };
  }
  return {
    kind: 'ready',
    risk: status.risk,
    required: status.required,
    missing: status.missing,
    unknown: status.unknown
  };
}

export function deviceCapabilityMapFromDevice(
  device: object | null | undefined
): DeviceCapabilityMap | undefined {
  if (!device) return undefined;
  const raw = device as Record<string, unknown>;
  const caps: DeviceCapabilityMap = {};
  const nested =
    raw.capabilities && typeof raw.capabilities === 'object'
      ? (raw.capabilities as DeviceCapabilityMap)
      : undefined;
  if (nested) Object.assign(caps, nested);

  for (const key of [
    'has_u2',
    'has_ocr',
    'has_tesseract',
    'has_image_match',
    'has_opencv',
    'supports_advanced_gestures',
    'supports_clipboard',
    'supports_file_ops',
    'supports_install_apk',
    'supports_screenshot',
    'supports_shell'
  ]) {
    if (key in raw) caps[key] = raw[key];
  }

  const touchMethod = String(raw.touch_method ?? '').toLowerCase();
  if (!('has_u2' in caps) && (raw.u2_ready != null || touchMethod)) {
    caps.has_u2 = Boolean(raw.u2_ready || touchMethod === 'u2');
  }
  if (!('supports_advanced_gestures' in caps) && 'has_u2' in caps) {
    caps.supports_advanced_gestures = caps.has_u2;
  }

  return Object.keys(caps).length ? caps : undefined;
}
