'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { Braces, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Switch } from '@/components/ui/switch';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ScrollArea } from '@/components/ui/scroll-area';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { cn } from '@/lib/utils';
import { mergeCampaignScenarioVariables as mergeCampaignScenarioVariablesModel } from './device-vars-json-model';
import { DeviceVarsFacebookTargetForm } from './device-vars-facebook-target-form';
import {
  DEVICE_TARGET_FORM_KEY,
  emptyDeviceTargetFormState,
  applyDeviceTargetFormState,
  isDeviceTargetFormControlledKey,
  removeDeviceTargetFormState
} from './device-vars-target-form-model';

export const DEFAULT_DEVICE_VARIABLES = {
  group_name: '',
  save_collection: ''
};

const VARIABLE_KEY_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;

function flattenVarValue(value: unknown): unknown {
  if (
    value !== null &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    'type' in value &&
    'default' in value
  ) {
    return (value as { default?: unknown }).default;
  }
  return value;
}

/** Flatten scenario/campaign variable defs to plain values (no default placeholder keys). */
export function flattenVariableDefinitions(
  raw?: Record<string, unknown> | null
) {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(raw ?? {})) {
    if (!VARIABLE_KEY_RE.test(key) || key.startsWith('__')) continue;
    out[key] = flattenVarValue(value);
  }
  return out;
}

export function buildDeviceVarsTemplate(
  baseVariables?: Record<string, unknown>
): Record<string, unknown> {
  const out = flattenVariableDefinitions(baseVariables);
  return Object.keys(out).length ? out : { ...DEFAULT_DEVICE_VARIABLES };
}

/** Resolve globals for device vars: scenario values are defaults, campaign values win per campaign. */
export function mergeCampaignScenarioVariables(
  campaignVariables?: Record<string, unknown> | null,
  scenarioVariables?: Record<string, unknown> | null
) {
  return mergeCampaignScenarioVariablesModel(
    campaignVariables,
    scenarioVariables
  );
}

/** From merged view (global ∪ edits), keep only keys that differ from global or are not in global — matches what we persist as device overrides. */
export function splitDeviceOverridesFromMerged(
  merged: Record<string, unknown>,
  globalFlat: Record<string, unknown>
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
  invalidRoot: 'JSON must be an object, e.g. {"group_name": "abc"}'
};

export function parseDeviceVarsJson(
  text: string,
  messages?: Partial<ParseDeviceVarsJsonMessages>
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

function formatScalarForInput(v: unknown): string {
  if (v === null || v === undefined) return '';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

/** Keep string vs number vs boolean stable when editing a single field. */
function coerceInputToValue(raw: string, previous: unknown): unknown {
  const trimmed = raw.trim();
  if (typeof previous === 'string') return raw;
  if (typeof previous === 'number') {
    const n = Number(trimmed);
    return Number.isFinite(n) ? n : raw;
  }
  if (typeof previous === 'boolean') {
    if (/^true$/i.test(trimmed)) return true;
    if (/^false$/i.test(trimmed)) return false;
    return raw;
  }
  if (trimmed === 'true' || trimmed === 'false') return trimmed === 'true';
  if (
    trimmed !== '' &&
    !Number.isNaN(Number(trimmed)) &&
    String(Number(trimmed)) === trimmed
  ) {
    return Number(trimmed);
  }
  if (
    Array.isArray(previous) ||
    (previous !== null && typeof previous === 'object')
  ) {
    try {
      return JSON.parse(trimmed);
    } catch {
      return raw;
    }
  }
  return raw;
}

type VariablesFieldGridProps = {
  entries: [string, unknown][];
  readOnly: boolean;
  onApply?: (key: string, value: unknown) => void;
  onRemove?: (key: string) => void;
  globalBaseline?: Record<string, unknown>;
  disabled?: boolean;
  globalHint?: (value: string) => string;
  removeLabel?: (key: string) => string;
};

function VariablesFieldGrid({
  entries,
  readOnly,
  onApply,
  onRemove,
  globalBaseline,
  disabled = false,
  globalHint,
  removeLabel
}: VariablesFieldGridProps) {
  if (entries.length === 0) return null;
  return (
    <ScrollArea className='max-h-[min(36vh,260px)] w-full rounded-md border bg-background'>
      <div className='divide-y'>
        {entries.map(([key, value]) => {
          const g = globalBaseline?.[key];
          const differs =
            readOnly === false &&
            g !== undefined &&
            JSON.stringify(g) !== JSON.stringify(value);
          const id = `dv-${key.replace(/[^a-zA-Z0-9_-]/g, '_')}`;
          return (
            <div
              key={key}
              className='grid gap-2 px-3 py-2.5 sm:grid-cols-[minmax(0,9.5rem)_1fr_auto] sm:items-center'
            >
              <div className='min-w-0'>
                <Label
                  htmlFor={id}
                  className='block truncate font-mono text-[11px] font-medium text-muted-foreground'
                  title={key}
                >
                  {key}
                </Label>
                {differs && globalHint ? (
                  <p
                    className='mt-0.5 truncate font-mono text-[10px] text-muted-foreground/90'
                    title={formatScalarForInput(g)}
                  >
                    {globalHint(formatScalarForInput(g))}
                  </p>
                ) : null}
              </div>
              {typeof value === 'boolean' && !readOnly && onApply ? (
                <Switch
                  id={id}
                  checked={value}
                  disabled={disabled}
                  onCheckedChange={(c) => onApply(key, c)}
                />
              ) : (
                <Input
                  id={id}
                  className='h-8 min-w-0 font-mono text-xs'
                  readOnly={readOnly}
                  disabled={disabled && !readOnly}
                  spellCheck={false}
                  value={formatScalarForInput(value)}
                  onChange={(e) => {
                    if (readOnly || !onApply) return;
                    onApply(key, coerceInputToValue(e.target.value, value));
                  }}
                />
              )}
              {!readOnly && onRemove ? (
                <Button
                  type='button'
                  variant='ghost'
                  size='icon'
                  className='size-8 justify-self-end text-muted-foreground hover:text-destructive'
                  disabled={disabled}
                  title={removeLabel?.(key)}
                  aria-label={removeLabel?.(key)}
                  onClick={() => onRemove(key)}
                >
                  <Trash2 className='size-4' />
                </Button>
              ) : null}
            </div>
          );
        })}
      </div>
    </ScrollArea>
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
  variant?: 'default' | 'assignment';
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
  variant = 'default'
}: DeviceVarsJsonPanelProps) {
  const t = useTranslations('components.deviceVarsJson');
  const [editorMode, setEditorMode] = useState<'form' | 'json'>('form');
  const [assignmentTab, setAssignmentTab] = useState<
    'targets' | 'advanced' | 'json'
  >('targets');
  const [specialForm, setSpecialForm] = useState<'none' | 'facebookTargets'>(
    'none'
  );
  const parseMsgs = useMemo(
    () => ({
      invalidJson: t('parseInvalidJson'),
      invalidRoot: t('parseInvalidRoot')
    }),
    [t]
  );
  const templateVars = buildDeviceVarsTemplate(baseVariables);
  let parsedDraft: Record<string, unknown> | null = null;
  try {
    parsedDraft = parseDeviceVarsJson(draft, parseMsgs);
  } catch {
    parsedDraft = null;
  }
  const hasTargetFormDraft =
    parsedDraft !== null &&
    Object.prototype.hasOwnProperty.call(parsedDraft, DEVICE_TARGET_FORM_KEY);

  useEffect(() => {
    if (!enabled || !hasTargetFormDraft) return;
    setEditorMode('form');
    setSpecialForm('facebookTargets');
  }, [draft, enabled, hasTargetFormDraft]);

  const globalPreview = globalVariablesPreview ?? {};
  const effectiveDeviceVarsForTemplate = useMemo(() => {
    if (!enabled) return {} as Record<string, unknown>;
    if (parsedDraft === null) return {};
    return parsedDraft;
  }, [enabled, parsedDraft]);

  const missingTemplateKeys = useMemo(() => {
    if (!enabled) return [];
    return Object.keys(templateVars)
      .filter((key) => !(key in effectiveDeviceVarsForTemplate))
      .slice(0, 16);
  }, [enabled, templateVars, effectiveDeviceVarsForTemplate]);

  const addTemplateKey = (key: string) => {
    const current = parsedDraft ?? {};
    onDraftChange(
      formatDeviceVarsJson({ ...current, [key]: templateVars[key] })
    );
  };
  const globalJson = JSON.stringify(globalPreview, null, 2);
  const hasGlobalPreview = Object.keys(globalPreview).length > 0;

  const overrideEditorValue = useMemo(() => {
    if (!enabled) return '';
    if (parsedDraft === null) return draft;
    return formatDeviceVarsJson(parsedDraft);
  }, [draft, enabled, parsedDraft]);

  const handleOverrideEditorChange = useCallback(
    (text: string) => {
      if (!enabled) return;
      try {
        const deviceOnly = parseDeviceVarsJson(text, parseMsgs);
        onDraftChange(formatDeviceVarsJson(deviceOnly));
      } catch {
        onDraftChange(text);
      }
    },
    [enabled, onDraftChange, parseMsgs]
  );

  const handleTargetFormChange = useCallback(
    (nextVars: Record<string, unknown>) => {
      if (!enabled) return;
      onDraftChange(formatDeviceVarsJson(nextVars));
    },
    [enabled, onDraftChange]
  );

  const handleSpecialFormChange = useCallback(
    (value: 'none' | 'facebookTargets') => {
      if (!enabled || parsedDraft === null) return;
      setSpecialForm(value);
      if (value === 'none') {
        onDraftChange(
          formatDeviceVarsJson(removeDeviceTargetFormState(parsedDraft))
        );
        return;
      }
      onDraftChange(
        formatDeviceVarsJson(
          hasTargetFormDraft
            ? parsedDraft
            : applyDeviceTargetFormState(
                parsedDraft,
                emptyDeviceTargetFormState()
              )
        )
      );
    },
    [enabled, hasTargetFormDraft, onDraftChange, parsedDraft]
  );

  const formVariableEntries = useMemo(() => {
    if (!enabled || parsedDraft === null) return [];
    return Object.entries(parsedDraft).filter(
      ([key]) => !isDeviceTargetFormControlledKey(key)
    );
  }, [enabled, parsedDraft]);

  const handleFormVariableChange = useCallback(
    (key: string, value: unknown) => {
      if (!enabled || parsedDraft === null) return;
      onDraftChange(formatDeviceVarsJson({ ...parsedDraft, [key]: value }));
    },
    [enabled, onDraftChange, parsedDraft]
  );

  const handleFormVariableRemove = useCallback(
    (key: string) => {
      if (!enabled || parsedDraft === null) return;
      const { [key]: _removed, ...nextVars } = parsedDraft;
      onDraftChange(formatDeviceVarsJson(nextVars));
    },
    [enabled, onDraftChange, parsedDraft]
  );

  const globalReadOnlyBlock = (
    <div className='flex min-h-0 flex-1 flex-col space-y-2'>
      <p className='text-xs font-medium'>{t('globalBlockTitle')}</p>
      {hasGlobalPreview ? (
        <Textarea
          readOnly
          className='min-h-[200px] flex-1 resize-none bg-muted/20 font-mono text-xs leading-5 text-muted-foreground'
          value={globalJson}
          spellCheck={false}
          aria-label={t('globalReadonlyAria')}
        />
      ) : (
        <p className='rounded-md border border-dashed bg-muted/10 px-3 py-8 text-center text-xs text-muted-foreground'>
          {t('globalEmpty')}
        </p>
      )}
    </div>
  );
  const renderAddGlobalKeyControl = () =>
    missingTemplateKeys.length > 0 ? (
      <Select
        value=''
        disabled={loading || parsedDraft === null}
        onValueChange={addTemplateKey}
      >
        <SelectTrigger className='h-8 w-full text-xs sm:w-48'>
          <SelectValue placeholder={t('addGlobalKeySelect')} />
        </SelectTrigger>
        <SelectContent>
          {missingTemplateKeys.map((key) => (
            <SelectItem key={key} value={key}>
              {key}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    ) : null;

  if (variant === 'assignment') {
    return (
      <div className={cn('flex min-h-0 flex-col', className)}>
        <div className='mb-3 flex shrink-0 items-center justify-between gap-3 rounded-md border bg-background px-3 py-3'>
          <div className='min-w-0'>
            <div className='flex items-center gap-2 text-sm font-medium'>
              <Braces size={13} />
              {t('title')}
            </div>
            {deviceLabel && (
              <p className='mt-0.5 truncate text-[11px] text-muted-foreground'>
                {deviceLabel}
              </p>
            )}
          </div>
          <div className='flex shrink-0 items-center gap-3 rounded-md border bg-muted/20 px-3 py-2'>
            <div className='hidden min-w-0 sm:block'>
              <p className='text-xs font-medium'>{t('toggleLabel')}</p>
              <p className='mt-0.5 max-w-72 truncate text-[11px] text-muted-foreground'>
                {enabled ? t('toggleDescriptionOn') : t('toggleDescriptionOff')}
              </p>
            </div>
            <Switch
              checked={enabled}
              disabled={loading}
              onCheckedChange={onEnabledChange}
              aria-label={enabled ? t('toggleAriaOn') : t('toggleAriaOff')}
            />
          </div>
        </div>

        {enabled ? (
          parsedDraft === null ? (
            <div className='flex min-h-0 flex-1 flex-col gap-3'>
              <div
                role='alert'
                className='rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive'
              >
                {t('formJsonInvalid')}
              </div>
              <Textarea
                className={cn(
                  'min-h-[300px] flex-1 resize-none font-mono text-xs leading-5',
                  editorClassName
                )}
                value={overrideEditorValue}
                disabled={loading}
                spellCheck={false}
                onChange={(event) =>
                  handleOverrideEditorChange(event.target.value)
                }
              />
            </div>
          ) : (
            <Tabs
              value={assignmentTab}
              onValueChange={(value) =>
                setAssignmentTab(value as 'targets' | 'advanced' | 'json')
              }
              className='min-h-0 flex-1 gap-3 overflow-hidden'
            >
              <TabsList className='grid h-9 w-full grid-cols-3 sm:w-[27rem]'>
                <TabsTrigger value='targets' className='text-xs'>
                  {t('targetFormTitle')}
                </TabsTrigger>
                <TabsTrigger value='advanced' className='text-xs'>
                  {t('otherVariablesTitle')}
                </TabsTrigger>
                <TabsTrigger value='json' className='text-xs'>
                  {t('jsonMode')}
                </TabsTrigger>
              </TabsList>

              <TabsContent
                value='targets'
                className='mt-0 min-h-0 overflow-hidden'
              >
                <section className='flex min-h-0 flex-col gap-4 rounded-md border bg-background p-4'>
                  <div className='min-w-0'>
                    <p className='text-sm font-medium'>
                      {t('targetFormTitle')}
                    </p>
                    <p className='mt-1 text-xs text-muted-foreground'>
                      {t('specialFormFacebookHint')}
                    </p>
                  </div>
                  <DeviceVarsFacebookTargetForm
                    vars={parsedDraft}
                    disabled={loading}
                    size='large'
                    onChange={handleTargetFormChange}
                  />
                </section>
              </TabsContent>

              <TabsContent
                value='advanced'
                className='mt-0 min-h-0 overflow-hidden'
              >
                <section className='flex min-h-0 flex-col gap-3 rounded-md border bg-background p-4'>
                  <div className='flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between'>
                    <p className='text-sm font-medium'>
                      {t('otherVariablesTitle')}
                    </p>
                    {renderAddGlobalKeyControl()}
                  </div>
                  {formVariableEntries.length > 0 ? (
                    <VariablesFieldGrid
                      entries={formVariableEntries}
                      readOnly={false}
                      disabled={loading}
                      onApply={handleFormVariableChange}
                      onRemove={handleFormVariableRemove}
                      globalBaseline={globalPreview}
                      globalHint={(value) => t('globalValueHint', { value })}
                      removeLabel={(key) => t('removeVariable', { key })}
                    />
                  ) : (
                    <p className='rounded-md border border-dashed bg-muted/10 px-3 py-8 text-center text-xs text-muted-foreground'>
                      {t('otherVariablesEmpty')}
                    </p>
                  )}
                </section>
              </TabsContent>

              <TabsContent value='json' className='mt-0 min-h-0'>
                <div className='flex min-h-0 flex-1 flex-col gap-3'>
                  {missingTemplateKeys.length > 0 ? (
                    <div className='flex justify-end'>
                      {renderAddGlobalKeyControl()}
                    </div>
                  ) : null}
                  <Textarea
                    className={cn(
                      'min-h-[360px] flex-1 resize-none font-mono text-xs leading-5 xl:min-h-[420px]',
                      editorClassName
                    )}
                    value={overrideEditorValue}
                    disabled={loading}
                    spellCheck={false}
                    onChange={(event) =>
                      handleOverrideEditorChange(event.target.value)
                    }
                  />
                </div>
              </TabsContent>
            </Tabs>
          )
        ) : (
          <div
            className={cn(
              'flex min-h-0 flex-1 flex-col gap-3 rounded-md border bg-background p-4',
              emptyClassName
            )}
          >
            {globalReadOnlyBlock}
          </div>
        )}

        <div className='mt-2 flex min-h-5 shrink-0 items-center justify-between gap-3 text-[11px]'>
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

  return (
    <div className={cn('flex min-h-0 flex-col', className)}>
      <div className='mb-3 flex shrink-0 items-center justify-between gap-3 rounded-md border bg-background px-3 py-3'>
        <div className='min-w-0'>
          <div className='flex items-center gap-2 text-sm font-medium'>
            <Braces size={13} />
            {t('title')}
          </div>
          {deviceLabel && (
            <p className='mt-0.5 truncate text-[11px] text-muted-foreground'>
              {deviceLabel}
            </p>
          )}
        </div>
        <div className='flex shrink-0 items-center gap-3 rounded-md border bg-muted/20 px-3 py-2'>
          <div className='hidden min-w-0 sm:block'>
            <p className='text-xs font-medium'>{t('toggleLabel')}</p>
            <p className='mt-0.5 max-w-72 truncate text-[11px] text-muted-foreground'>
              {enabled ? t('toggleDescriptionOn') : t('toggleDescriptionOff')}
            </p>
          </div>
          <Switch
            checked={enabled}
            disabled={loading}
            onCheckedChange={onEnabledChange}
            aria-label={enabled ? t('toggleAriaOn') : t('toggleAriaOff')}
          />
        </div>
      </div>

      {enabled ? (
        <div className='flex min-h-0 flex-1 flex-col space-y-3'>
          <Tabs
            value={editorMode}
            onValueChange={(value) => setEditorMode(value as 'form' | 'json')}
          >
            <TabsList className='grid h-9 w-full grid-cols-2 sm:w-64'>
              <TabsTrigger value='form' className='text-xs'>
                {t('formMode')}
              </TabsTrigger>
              <TabsTrigger value='json' className='text-xs'>
                {t('jsonMode')}
              </TabsTrigger>
            </TabsList>
          </Tabs>

          {editorMode === 'form' ? (
            parsedDraft === null ? (
              <div
                role='alert'
                className='rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive'
              >
                {t('formJsonInvalid')}
              </div>
            ) : (
              <ScrollArea className='min-h-0 min-w-0 flex-1 overflow-hidden pr-3'>
                <div className='min-w-0 max-w-full space-y-3 overflow-hidden pb-1'>
                  <section className='min-w-0 space-y-3 overflow-hidden rounded-md border bg-background p-3'>
                    <div className='flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between'>
                      <p className='text-xs font-medium'>
                        {t('otherVariablesTitle')}
                      </p>
                      {missingTemplateKeys.length > 0 ? (
                        <Select
                          value=''
                          disabled={loading || parsedDraft === null}
                          onValueChange={addTemplateKey}
                        >
                          <SelectTrigger className='h-8 w-full text-xs sm:w-48'>
                            <SelectValue
                              placeholder={t('addGlobalKeySelect')}
                            />
                          </SelectTrigger>
                          <SelectContent>
                            {missingTemplateKeys.map((key) => (
                              <SelectItem key={key} value={key}>
                                {key}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      ) : null}
                    </div>
                    {formVariableEntries.length > 0 ? (
                      <VariablesFieldGrid
                        entries={formVariableEntries}
                        readOnly={false}
                        disabled={loading}
                        onApply={handleFormVariableChange}
                        onRemove={handleFormVariableRemove}
                        globalBaseline={globalPreview}
                        globalHint={(value) => t('globalValueHint', { value })}
                        removeLabel={(key) => t('removeVariable', { key })}
                      />
                    ) : (
                      <p className='rounded-md border border-dashed bg-muted/10 px-3 py-6 text-center text-xs text-muted-foreground'>
                        {t('otherVariablesEmpty')}
                      </p>
                    )}
                  </section>

                  <section className='min-w-0 space-y-4 overflow-hidden rounded-md border bg-background p-4'>
                    <div className='grid min-w-0 gap-3 sm:grid-cols-[minmax(0,1fr)_minmax(0,14rem)] sm:items-end'>
                      <div className='min-w-0'>
                        <p className='text-sm font-medium'>
                          {t('targetFormTitle')}
                        </p>
                        <p className='mt-1 text-xs text-muted-foreground'>
                          {specialForm === 'facebookTargets'
                            ? t('specialFormFacebookHint')
                            : t('specialFormNoneHint')}
                        </p>
                      </div>
                      <Select
                        value={specialForm}
                        disabled={loading}
                        onValueChange={(value) =>
                          handleSpecialFormChange(
                            value as 'none' | 'facebookTargets'
                          )
                        }
                      >
                        <SelectTrigger className='h-9 w-full min-w-0 text-sm [&_[data-slot=select-value]]:truncate'>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value='none'>
                            {t('specialFormNone')}
                          </SelectItem>
                          <SelectItem value='facebookTargets'>
                            {t('specialFormFacebook')}
                          </SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    {specialForm === 'facebookTargets' ? (
                      <DeviceVarsFacebookTargetForm
                        vars={parsedDraft}
                        disabled={loading}
                        onChange={handleTargetFormChange}
                      />
                    ) : null}
                  </section>
                </div>
              </ScrollArea>
            )
          ) : (
            <>
              {missingTemplateKeys.length > 0 && (
                <div className='flex justify-end'>
                  <Select
                    value=''
                    disabled={loading || parsedDraft === null}
                    onValueChange={addTemplateKey}
                  >
                    <SelectTrigger className='h-8 w-full text-xs sm:w-48'>
                      <SelectValue placeholder={t('addGlobalKeySelect')} />
                    </SelectTrigger>
                    <SelectContent>
                      {missingTemplateKeys.map((key) => (
                        <SelectItem key={key} value={key}>
                          {key}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              )}
              <Textarea
                className={cn(
                  'min-h-[200px] flex-1 resize-none font-mono text-xs leading-5',
                  editorClassName
                )}
                value={overrideEditorValue}
                disabled={loading}
                spellCheck={false}
                onChange={(event) =>
                  handleOverrideEditorChange(event.target.value)
                }
              />
            </>
          )}
        </div>
      ) : (
        <div
          className={cn(
            'flex min-h-0 flex-1 flex-col gap-3 rounded-md border bg-background p-4',
            emptyClassName
          )}
        >
          {globalReadOnlyBlock}
        </div>
      )}

      <div className='mt-2 flex min-h-5 shrink-0 items-center justify-between gap-3 text-[11px]'>
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
