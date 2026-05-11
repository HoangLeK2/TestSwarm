'use client';

import { useCallback, useMemo } from 'react';
import { useTranslations } from 'next-intl';
import { Braces, Plus } from 'lucide-react';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export const DEFAULT_DEVICE_VARIABLES = {
  group_name: '',
  save_collection: '',
};

const VARIABLE_KEY_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;

function flattenVarValue(value: unknown): unknown {
  if (
    value !== null
    && typeof value === 'object'
    && !Array.isArray(value)
    && 'type' in value
    && 'default' in value
  ) {
    return (value as { default?: unknown }).default;
  }
  return value;
}

/** Flatten scenario/campaign variable defs to plain values (no default placeholder keys). */
export function flattenVariableDefinitions(raw?: Record<string, unknown> | null) {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw ?? {})) {
    if (!VARIABLE_KEY_RE.test(key) || key.startsWith('__')) continue;
    out[key] = flattenVarValue(value);
  }
  return out;
}

export function buildDeviceVarsTemplate(baseVariables?: Record<string, unknown>): Record<string, unknown> {
  const out = flattenVariableDefinitions(baseVariables);
  return Object.keys(out).length ? out : { ...DEFAULT_DEVICE_VARIABLES };
}

/** Same resolution stack as runtime: campaign then scenario (scenario wins on same key). */
export function mergeCampaignScenarioVariables(
  campaignVariables?: Record<string, unknown> | null,
  scenarioVariables?: Record<string, unknown> | null,
) {
  return {
    ...flattenVariableDefinitions(campaignVariables ?? undefined),
    ...flattenVariableDefinitions(scenarioVariables ?? undefined),
  };
}

/** From merged view (global ∪ edits), keep only keys that differ from global or are not in global — matches what we persist as device overrides. */
export function splitDeviceOverridesFromMerged(
  merged: Record<string, unknown>,
  globalFlat: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(merged)) {
    if (!(k in globalFlat)) {
      out[k] = v;
      continue;
    }
    if (JSON.stringify(globalFlat[k]) !== JSON.stringify(v)) {
      out[k] = v;
    }
  }
  return out;
}

export type ParseDeviceVarsJsonMessages = {
  invalidJson: string;
  invalidRoot: string;
};

const DEFAULT_PARSE_MESSAGES: ParseDeviceVarsJsonMessages = {
  invalidJson: 'Invalid JSON (syntax error).',
  invalidRoot: 'JSON must be an object, e.g. {"group_name": "abc"}',
};

export function parseDeviceVarsJson(
  text: string,
  messages?: Partial<ParseDeviceVarsJsonMessages>,
): Record<string, unknown> {
  const m = { ...DEFAULT_PARSE_MESSAGES, ...messages };
  let parsed: unknown;
  try {
    parsed = JSON.parse(text || '{}');
  } catch {
    throw new Error(m.invalidJson);
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(m.invalidRoot);
  }
  return parsed as Record<string, unknown>;
}

export function formatDeviceVarsJson(vars: Record<string, unknown>) {
  return JSON.stringify(vars, null, 2);
}

export function formatInitialDeviceVars(
  vars: Record<string, unknown>,
  baseVariables?: Record<string, unknown>,
) {
  return formatDeviceVarsJson(
    Object.keys(vars).length ? vars : buildDeviceVarsTemplate(baseVariables),
  );
}

type DeviceVarsJsonPanelProps = {
  enabled: boolean;
  onEnabledChange: (enabled: boolean) => void;
  draft: string;
  onDraftChange: (value: string) => void;
  loading?: boolean;
  jsonError?: string;
  deviceLabel?: string;
  baseVariables?: Record<string, unknown>;
  /** Merged campaign + scenario globals (read-only). Shown when device overrides are off; also shown above editor when on. */
  globalVariablesPreview?: Record<string, unknown>;
  className?: string;
  editorClassName?: string;
  emptyClassName?: string;
};

export function DeviceVarsJsonPanel({
  enabled,
  onEnabledChange,
  draft,
  onDraftChange,
  loading = false,
  jsonError = '',
  deviceLabel,
  baseVariables,
  globalVariablesPreview,
  className,
  editorClassName,
  emptyClassName,
}: DeviceVarsJsonPanelProps) {
  const t = useTranslations('components.deviceVarsJson');
  const parseMsgs = useMemo(
    () => ({
      invalidJson: t('parseInvalidJson'),
      invalidRoot: t('parseInvalidRoot'),
    }),
    [t],
  );
  const templateVars = buildDeviceVarsTemplate(baseVariables);
  let parsedDraft: Record<string, unknown> | null = null;
  try {
    parsedDraft = parseDeviceVarsJson(draft, parseMsgs);
  } catch {
    parsedDraft = null;
  }

  const globalPreview = globalVariablesPreview ?? {};
  /** Keys already shown in merged editor (global ∪ device) — template chips only for keys truly absent there. */
  const effectiveMergedForTemplate = useMemo(() => {
    if (!enabled) return {} as Record<string, unknown>;
    if (parsedDraft === null) return { ...globalPreview };
    return { ...globalPreview, ...parsedDraft };
  }, [enabled, globalPreview, parsedDraft]);

  const missingTemplateKeys = useMemo(() => {
    if (!enabled) return [];
    return Object.keys(templateVars)
      .filter((key) => !(key in effectiveMergedForTemplate))
      .slice(0, 16);
  }, [enabled, templateVars, effectiveMergedForTemplate]);

  const addTemplateKey = (key: string) => {
    const current = parsedDraft ?? {};
    onDraftChange(formatDeviceVarsJson({ ...current, [key]: templateVars[key] }));
  };
  const globalJson = JSON.stringify(globalPreview, null, 2);
  const hasGlobalPreview = Object.keys(globalPreview).length > 0;

  const mergedEditorValue = useMemo(() => {
    if (!enabled) return '';
    if (parsedDraft === null) return draft;
    return formatDeviceVarsJson({ ...globalPreview, ...parsedDraft });
  }, [draft, enabled, globalPreview, parsedDraft]);

  const handleMergedEditorChange = useCallback(
    (text: string) => {
      if (!enabled) return;
      try {
        const merged = parseDeviceVarsJson(text, parseMsgs);
        const deviceOnly = splitDeviceOverridesFromMerged(merged, globalPreview);
        onDraftChange(formatDeviceVarsJson(deviceOnly));
      } catch {
        onDraftChange(text);
      }
    },
    [enabled, globalPreview, onDraftChange, parseMsgs],
  );

  const globalReadOnlyBlock = (
    <div className='space-y-1.5'>
      <p className='text-[11px] font-medium text-muted-foreground'>
        {t('globalBlockTitle')}
      </p>
      {hasGlobalPreview ? (
        <Textarea
          readOnly
          className='min-h-[200px] resize-none bg-muted/30 font-mono text-xs leading-5 text-muted-foreground'
          value={globalJson}
          spellCheck={false}
          aria-label={t('globalReadonlyAria')}
        />
      ) : (
        <p className='rounded-md border border-dashed bg-muted/10 px-3 py-6 text-center text-[11px] text-muted-foreground'>
          {t('globalEmpty')}
        </p>
      )}
    </div>
  );

  return (
    <div className={cn('min-h-0', className)}>
      <div className='mb-3 flex items-center justify-between gap-3'>
        <div className='min-w-0'>
          <div className='flex items-center gap-2 text-xs font-medium'>
            <Braces size={13} />
            {t('title')}
          </div>
          {deviceLabel && (
            <p className='mt-0.5 truncate text-[11px] text-muted-foreground'>
              {deviceLabel}
            </p>
          )}
        </div>
      </div>

      <div className='mb-3 flex items-center justify-between rounded border bg-muted/20 px-3 py-2'>
        <div className='min-w-0'>
          <p className='text-xs font-medium'>{t('toggleLabel')}</p>
          <p className='mt-0.5 text-[11px] text-muted-foreground'>
            {t('toggleDescription')}
          </p>
        </div>
        <Switch
          checked={enabled}
          disabled={loading}
          onCheckedChange={onEnabledChange}
          aria-label={t('toggleAria')}
        />
      </div>

      {enabled ? (
        <div className='space-y-2'>
          {missingTemplateKeys.length > 0 && (
            <div className='flex flex-wrap items-center gap-1.5'>
              <span className='mr-1 text-[11px] text-muted-foreground'>{t('addGlobalKeyLabel')}</span>
              {missingTemplateKeys.map((key) => (
                <Button
                  key={key}
                  type='button'
                  size='sm'
                  variant='outline'
                  className='h-6 gap-1 rounded px-2 font-mono text-[11px]'
                  disabled={loading || parsedDraft === null}
                  onClick={() => addTemplateKey(key)}
                >
                  <Plus size={11} />
                  {key}
                </Button>
              ))}
            </div>
          )}
          <Textarea
            className={cn('min-h-[420px] resize-none font-mono text-xs leading-5', editorClassName)}
            value={mergedEditorValue}
            disabled={loading}
            spellCheck={false}
            onChange={(event) => handleMergedEditorChange(event.target.value)}
          />
        </div>
      ) : (
        <div
          className={cn(
            'flex min-h-0 flex-col gap-3 rounded-md border border-dashed bg-muted/10 p-4',
            emptyClassName,
          )}
        >
          <p className='text-center text-xs text-muted-foreground'>
            {t('modeOffHint')}
          </p>
          {globalReadOnlyBlock}
        </div>
      )}

      <div className='mt-2 flex min-h-5 items-center justify-between gap-3 text-[11px]'>
        <span className='text-muted-foreground'>
          {loading
            ? t('footerLoading')
            : enabled
              ? t('footerMergedEditor')
              : t('footerUsingGlobal')}
        </span>
        {jsonError && <span className='text-destructive'>{jsonError}</span>}
      </div>
    </div>
  );
}
