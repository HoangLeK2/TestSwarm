'use client';

import { useEffect, useState, type ReactNode } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Plus,
  Trash2
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { FlowStep } from '../scenario-steps/types';
import {
  addManualLoginChallenge,
  addLocator,
  addPopupWatcher,
  appAutomationProfile,
  csvToList,
  ensureFormRecipe,
  ensureLoginRecipe,
  firstCandidate,
  getLoginSetupStatus,
  listToCsv,
  locatorNames,
  patchFormField,
  patchFormRecipe,
  patchLocator,
  patchLoginField,
  patchPostSubmitLoginField,
  patchLoginRecipe,
  patchLoginTarget,
  patchManualLoginChallenge,
  patchPopupWatcher,
  patchProfile,
  removeFormField,
  removeLocator,
  removeManualLoginChallenge,
  removePopupWatcher
} from './app-automation-profile-model';
import {
  F,
  StepPanelField,
  StepPanelHint,
  StepPanelToggle
} from './step-panel-primitives';

type Props = {
  step: FlowStep;
  update: (patch: Partial<FlowStep>) => void;
  availableVariables?: string[];
};

type AppAutomationT = ReturnType<
  typeof useTranslations<'campaignsFeature.stepEditor.appAutomation'>
>;

const LOGIN_FIELD_NAMES = ['username', 'password'] as const;
const POST_SUBMIT_LOGIN_FIELD_NAMES = ['auth_code'] as const;
type LoginTargetField =
  | (typeof LOGIN_FIELD_NAMES)[number]
  | (typeof POST_SUBMIT_LOGIN_FIELD_NAMES)[number];

const KNOWN_LOGIN_APPS = [
  { package: 'com.facebook.katana', label: 'Facebook' },
  { package: 'com.facebook.lite', label: 'Facebook Lite' },
  { package: 'com.android.chrome', label: 'Chrome' },
  { package: 'com.google.android.youtube', label: 'YouTube' },
  { package: 'com.zhiliaoapp.musically', label: 'TikTok' },
  { package: 'com.ss.android.ugc.trill', label: 'TikTok (Asia)' }
] as const;

const LOGIN_FIELD_LABEL_KEYS = {
  username: 'loginFields.username',
  password: 'loginFields.password',
  auth_code: 'loginFields.authCode'
} as const;

const LOGIN_FIELD_DEFAULT_VALUE_FROM = {
  username: 'account.username',
  password: 'account.password',
  auth_code: 'account.totp_code'
} as const;

const LOGIN_FIELD_VALUE_REF_QUICK_PICKS = {
  username: [
    'account.username',
    'account.email',
    'account.display_name',
    'scenario.username'
  ],
  password: ['account.password', 'secret.login_password'],
  auth_code: ['account.totp_code', 'variables.auth_code', 'scenario.auth_code']
} as const satisfies Record<LoginTargetField, readonly string[]>;

function commit(update: Props['update'], next: FlowStep) {
  update(next as Partial<FlowStep>);
}

/** Chip wording for the refs the picker offers, keyed by the ref itself. */
const QUICK_PICK_LABEL_KEYS: Record<string, string> = {
  'account.username': 'loginUi.quickPicks.accountUsername',
  'account.email': 'loginUi.quickPicks.accountEmail',
  'account.display_name': 'loginUi.quickPicks.accountDisplayName',
  'scenario.username': 'loginUi.quickPicks.scenarioUsername',
  'account.password': 'loginUi.quickPicks.accountPassword',
  'secret.login_password': 'loginUi.quickPicks.securePassword',
  'account.totp_code': 'loginUi.quickPicks.accountTotpCode',
  'variables.auth_code': 'loginUi.quickPicks.authCodeVariable',
  'scenario.auth_code': 'loginUi.quickPicks.authCodeScenario'
};

/**
 * What a quick-pick chip reads as.
 *
 * The chips used to print the raw ref (`account.username`), which says nothing
 * to an operator picking where a login field gets its value. The ref stays on
 * the tooltip for anyone wiring a scenario by hand.
 */
function quickPickLabel(ref: string, t: AppAutomationT): string {
  const key = QUICK_PICK_LABEL_KEYS[ref];
  if (key) return t(key);
  const variable = ref.startsWith('variables.') ? ref.slice(10) : '';
  return variable ? t('loginUi.quickPicks.variable', { name: variable }) : ref;
}

function ValueRefQuickPicks({
  refs,
  selected,
  onPick,
  t
}: {
  refs: readonly string[];
  selected: string;
  onPick: (ref: string) => void;
  t: AppAutomationT;
}) {
  const uniqueRefs = Array.from(new Set(refs.filter(Boolean)));
  if (uniqueRefs.length === 0) return null;
  return (
    <div className='mt-2 flex flex-wrap gap-1.5'>
      {uniqueRefs.map((ref) => {
        const active = ref === selected;
        return (
          <Button
            key={ref}
            type='button'
            size='sm'
            variant={active ? 'default' : 'outline'}
            className='h-7 max-w-full px-2 text-[11px]'
            onClick={() => onPick(ref)}
            title={ref}
          >
            <span className='truncate'>{quickPickLabel(ref, t)}</span>
          </Button>
        );
      })}
    </div>
  );
}

function MiniSection({
  title,
  children
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <div className='space-y-3 border-t border-border/60 pt-3 first:border-t-0 first:pt-0'>
      <div className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
        {title}
      </div>
      {children}
    </div>
  );
}

function ValueRefSelect({
  value,
  onChange,
  availableVariables = [],
  t
}: {
  value: string;
  onChange: (next: string) => void;
  availableVariables?: string[];
  t: AppAutomationT;
}) {
  const variableOptions = availableVariables.map((name) => `variables.${name}`);
  const options = [
    'account.username',
    'account.display_name',
    'account.platform',
    'account.password',
    'account.email',
    'account.totp_code',
    'secret.login_password',
    'scenario.username',
    'scenario.auth_code',
    ...variableOptions
  ];
  return (
    <select
      className='h-8 w-full rounded-md border border-input bg-background px-2 py-1.5 font-mono text-xs'
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value=''>{t('valueFromPlaceholder')}</option>
      {options.map((option) => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
    </select>
  );
}

function LocatorEditor({ step, update, t }: Props & { t: AppAutomationT }) {
  const profile = appAutomationProfile(step);
  const names = locatorNames(profile);
  return (
    <MiniSection title={t('sections.locators')}>
      {names.length === 0 ? (
        <StepPanelHint>{t('emptyLocators')}</StepPanelHint>
      ) : null}
      <div className='space-y-2'>
        {names.map((name) => {
          const locator = profile.semantic_locators?.[name];
          const candidate = firstCandidate(locator);
          return (
            <div
              key={name}
              className='space-y-2 rounded-md border border-border/60 bg-background/70 p-2'
            >
              <div className='flex min-w-0 items-center gap-2'>
                <Input
                  className='h-8 min-w-0 flex-1 font-mono text-xs'
                  value={name}
                  readOnly
                />
                <Button
                  type='button'
                  size='icon'
                  variant='ghost'
                  className='size-8 shrink-0'
                  aria-label={t('actions.removeLocator')}
                  onClick={() => commit(update, removeLocator(step, name))}
                >
                  <Trash2 size={14} />
                </Button>
              </div>
              <div className='grid gap-2 sm:grid-cols-2'>
                <F label={t('fields.resourceIdContains')}>
                  <Input
                    className='h-8 font-mono text-xs'
                    value={candidate.resource_id_contains ?? ''}
                    onChange={(e) =>
                      commit(
                        update,
                        patchLocator(step, name, {
                          resource_id_contains: e.target.value || undefined
                        })
                      )
                    }
                  />
                </F>
                <F label={t('fields.descriptionContains')}>
                  <Input
                    className='h-8 font-mono text-xs'
                    value={candidate.description_contains ?? ''}
                    onChange={(e) =>
                      commit(
                        update,
                        patchLocator(step, name, {
                          description_contains: e.target.value || undefined
                        })
                      )
                    }
                  />
                </F>
                <F label={t('fields.textNear')}>
                  <Input
                    className='h-8 text-xs'
                    value={listToCsv(candidate.text_near)}
                    onChange={(e) =>
                      commit(
                        update,
                        patchLocator(step, name, {
                          text_near: csvToList(e.target.value)
                        })
                      )
                    }
                  />
                </F>
                <F label={t('fields.targetClass')}>
                  <Input
                    className='h-8 font-mono text-xs'
                    value={candidate.target_class ?? ''}
                    placeholder='android.widget.EditText'
                    onChange={(e) =>
                      commit(
                        update,
                        patchLocator(step, name, {
                          target_class: e.target.value || undefined
                        })
                      )
                    }
                  />
                </F>
              </div>
              <div className='grid gap-2 sm:grid-cols-3'>
                <F label={t('fields.by')}>
                  <select
                    className='h-8 w-full rounded-md border border-input bg-background px-2 text-xs'
                    value={candidate.by ?? ''}
                    onChange={(e) =>
                      commit(
                        update,
                        patchLocator(step, name, {
                          by: e.target.value || undefined
                        })
                      )
                    }
                  >
                    <option value=''>{t('options.none')}</option>
                    <option value='text'>{t('byOptions.text')}</option>
                    <option value='resource-id'>
                      {t('byOptions.resourceId')}
                    </option>
                    <option value='description'>
                      {t('byOptions.description')}
                    </option>
                    <option value='class name'>
                      {t('byOptions.className')}
                    </option>
                  </select>
                </F>
                <F label={t('fields.value')}>
                  <Input
                    className='h-8 font-mono text-xs'
                    value={candidate.value ?? ''}
                    onChange={(e) =>
                      commit(
                        update,
                        patchLocator(step, name, {
                          value: e.target.value || undefined
                        })
                      )
                    }
                  />
                </F>
                <F label={t('fields.region')}>
                  <select
                    className='h-8 w-full rounded-md border border-input bg-background px-2 text-xs'
                    value={candidate.region ?? ''}
                    onChange={(e) =>
                      commit(
                        update,
                        patchLocator(step, name, {
                          region: e.target.value || undefined
                        })
                      )
                    }
                  >
                    <option value=''>{t('options.any')}</option>
                    <option value='top'>{t('regions.top')}</option>
                    <option value='bottom'>{t('regions.bottom')}</option>
                    <option value='left'>{t('regions.left')}</option>
                    <option value='right'>{t('regions.right')}</option>
                    <option value='center'>{t('regions.center')}</option>
                    <option value='form'>{t('regions.form')}</option>
                  </select>
                </F>
              </div>
              <StepPanelToggle
                label={t('fields.allowCoordinateFallback')}
                checked={Boolean(candidate.allow_coordinate_fallback)}
                onCheckedChange={(checked) =>
                  commit(
                    update,
                    patchLocator(step, name, {
                      allow_coordinate_fallback: checked
                    })
                  )
                }
              />
            </div>
          );
        })}
      </div>
      <Button
        type='button'
        size='sm'
        variant='outline'
        className='h-8 gap-1.5 text-xs'
        onClick={() => commit(update, addLocator(step))}
      >
        <Plus size={14} />
        {t('actions.addLocator')}
      </Button>
    </MiniSection>
  );
}

function LoginEditor({
  step,
  update,
  availableVariables = [],
  t
}: Props & { t: AppAutomationT }) {
  const profile = appAutomationProfile(step);
  const recipe = ensureLoginRecipe(profile);
  const fields = recipe.fields ?? {};
  const status = getLoginSetupStatus(step);
  const loggedInText = listToCsv(recipe.detect_logged_in?.any_text);
  const submitText = listToCsv(recipe.submit?.tap_text_any);
  const postSubmitText = listToCsv(recipe.post_submit?.tap_text_any);
  const manualChallenges = recipe.manual_challenges ?? [];
  const challengeLocators = locatorNames(profile);

  const packageValue = profile.package ?? '';
  const detectedPackagePreset = KNOWN_LOGIN_APPS.some(
    (app) => app.package === packageValue
  )
    ? packageValue
    : packageValue
      ? 'custom'
      : '';
  const [customPackageMode, setCustomPackageMode] = useState(
    detectedPackagePreset === 'custom'
  );
  const loginStepIdentity = String(
    (step as Record<string, unknown>)._fgId ??
      (step as Record<string, unknown>).id ??
      step.type
  );
  useEffect(() => {
    setCustomPackageMode(detectedPackagePreset === 'custom');
  }, [detectedPackagePreset, loginStepIdentity]);
  const packagePreset =
    detectedPackagePreset === 'custom' ||
    (customPackageMode && !detectedPackagePreset)
      ? 'custom'
      : detectedPackagePreset;

  const patchTargetValue = (
    fieldName: LoginTargetField,
    mode: 'resource-id' | 'description' | 'text',
    value: string
  ) => {
    commit(
      update,
      patchLoginTarget(step, fieldName, {
        resource_id_contains: mode === 'resource-id' ? value : undefined,
        description_contains: mode === 'description' ? value : undefined,
        by: mode === 'text' ? 'text' : undefined,
        value: mode === 'text' ? value : undefined
      })
    );
  };

  return (
    <div className='space-y-3'>
      <div
        className={`flex gap-2.5 rounded-lg border p-3 ${
          status.ready
            ? 'border-emerald-500/30 bg-emerald-500/5'
            : 'border-amber-500/30 bg-amber-500/5'
        }`}
      >
        {status.ready ? (
          <CheckCircle2 className='mt-0.5 size-4 shrink-0 text-emerald-600' />
        ) : (
          <AlertCircle className='mt-0.5 size-4 shrink-0 text-amber-600' />
        )}
        <div className='min-w-0 space-y-1'>
          <div className='text-xs font-semibold'>
            {status.ready
              ? t('loginUi.statusReady')
              : t('loginUi.statusMissing', {
                  count: status.missing.length
                })}
          </div>
          <p className='text-[11px] leading-relaxed text-muted-foreground'>
            {status.ready
              ? t('loginUi.readyDescription')
              : status.missing
                  .map((item) => t(`loginUi.missing.${item}`))
                  .join(' · ')}
          </p>
        </div>
      </div>

      <StepPanelHint>{t('loginUi.intro')}</StepPanelHint>

      <div className='space-y-3 rounded-lg border border-border/60 bg-background/70 p-3'>
        <div className='text-xs font-semibold'>{t('loginUi.application')}</div>
        <F label={t('loginUi.applicationLabel')}>
          <select
            className='h-9 w-full rounded-md border border-input bg-background px-2 text-xs'
            value={packagePreset}
            onChange={(e) => {
              const next = e.target.value;
              setCustomPackageMode(next === 'custom');
              if (next === 'custom') return;
              commit(
                update,
                patchProfile(step, {
                  package: next
                })
              );
            }}
          >
            <option value=''>{t('loginUi.applicationPlaceholder')}</option>
            {KNOWN_LOGIN_APPS.map((app) => (
              <option key={app.package} value={app.package}>
                {app.label}
              </option>
            ))}
            <option value='custom'>{t('loginUi.customApplication')}</option>
          </select>
        </F>
        {packagePreset === 'custom' ? (
          <F label={t('fields.package')}>
            <Input
              className='h-8 font-mono text-xs'
              value={packageValue}
              onChange={(e) =>
                commit(update, patchProfile(step, { package: e.target.value }))
              }
            />
          </F>
        ) : null}
      </div>

      <div className='space-y-3 rounded-lg border border-border/60 bg-background/70 p-3'>
        <div>
          <div className='text-xs font-semibold'>
            {t('loginUi.loggedInTitle')}
          </div>
          <p className='mt-1 text-[11px] leading-relaxed text-muted-foreground'>
            {t('loginUi.loggedInDescription')}
          </p>
        </div>
        <F label={t('loginUi.loggedInLabel')}>
          <Input
            className='h-9 text-xs'
            value={loggedInText}
            placeholder={t('loginUi.loggedInPlaceholder')}
            onChange={(e) =>
              commit(
                update,
                patchLoginRecipe(step, {
                  detect_logged_in: { any_text: csvToList(e.target.value) }
                })
              )
            }
          />
        </F>
      </div>

      <div className='space-y-2'>
        <div className='px-0.5'>
          <div className='text-xs font-semibold'>
            {t('loginUi.credentialsTitle')}
          </div>
          <p className='mt-1 text-[11px] leading-relaxed text-muted-foreground'>
            {t('loginUi.credentialsDescription')}
          </p>
        </div>
        {LOGIN_FIELD_NAMES.map((fieldName) => {
          const field = fields[fieldName];
          const locator = field?.locator
            ? profile.semantic_locators?.[field.locator]
            : undefined;
          const candidate = firstCandidate(locator);
          const targetMode =
            candidate.description_contains != null ||
            candidate.by === 'description'
              ? 'description'
              : candidate.by === 'text'
                ? 'text'
                : 'resource-id';
          const targetValue =
            targetMode === 'description'
              ? (candidate.description_contains ??
                (candidate.by === 'description' ? candidate.value : '') ??
                '')
              : targetMode === 'text'
                ? (candidate.value ?? '')
                : (candidate.resource_id_contains ??
                  (candidate.by === 'resource-id' ? candidate.value : '') ??
                  '');
          const fieldReady = !status.missing.includes(fieldName);
          const defaultValueFrom = LOGIN_FIELD_DEFAULT_VALUE_FROM[fieldName];
          const selectedValueFrom = field?.value_from ?? defaultValueFrom;
          const quickPickRefs = [
            ...LOGIN_FIELD_VALUE_REF_QUICK_PICKS[fieldName],
            ...availableVariables.map((name) => `variables.${name}`)
          ];

          return (
            <div
              key={fieldName}
              className='space-y-3 rounded-lg border border-border/60 bg-background/70 p-3'
            >
              <div className='flex items-center justify-between gap-2'>
                <div className='text-xs font-semibold'>
                  {t(LOGIN_FIELD_LABEL_KEYS[fieldName])}
                </div>
                <span
                  className={`text-[10px] font-medium ${
                    fieldReady ? 'text-emerald-600' : 'text-amber-600'
                  }`}
                >
                  {fieldReady
                    ? t('loginUi.fieldReady')
                    : t('loginUi.fieldMissing')}
                </span>
              </div>

              <F label={t('loginUi.valueSource')}>
                <select
                  className='h-9 w-full rounded-md border border-input bg-background px-2 text-xs'
                  value={selectedValueFrom}
                  onChange={(e) =>
                    commit(
                      update,
                      patchLoginField(step, fieldName, {
                        value_from: e.target.value
                      })
                    )
                  }
                >
                  {fieldName === 'username' ? (
                    <>
                      <option value='account.username'>
                        {t('loginUi.sources.accountUsername')}
                      </option>
                      <option value='account.email'>
                        {t('loginUi.sources.accountEmail')}
                      </option>
                      <option value='account.display_name'>
                        {t('loginUi.sources.accountDisplayName')}
                      </option>
                      <option value='scenario.username'>
                        {t('loginUi.sources.scenarioUsername')}
                      </option>
                    </>
                  ) : (
                    <>
                      <option value='account.password'>
                        {t('loginUi.sources.accountPassword')}
                      </option>
                      <option value='secret.login_password'>
                        {t('loginUi.sources.securePassword')}
                      </option>
                    </>
                  )}
                  {availableVariables.map((name) => (
                    <option key={name} value={`variables.${name}`}>
                      {t('loginUi.sources.variable', { name })}
                    </option>
                  ))}
                </select>
                <ValueRefQuickPicks
                  refs={quickPickRefs}
                  selected={selectedValueFrom}
                  t={t}
                  onPick={(ref) =>
                    commit(
                      update,
                      patchLoginField(step, fieldName, {
                        value_from: ref
                      })
                    )
                  }
                />
              </F>

              <div className='grid gap-2 sm:grid-cols-[0.8fr_1.2fr]'>
                <F label={t('loginUi.findFieldBy')}>
                  <select
                    className='h-9 w-full rounded-md border border-input bg-background px-2 text-xs'
                    value={targetMode}
                    onChange={(e) =>
                      patchTargetValue(
                        fieldName,
                        e.target.value as
                          | 'resource-id'
                          | 'description'
                          | 'text',
                        targetValue
                      )
                    }
                  >
                    <option value='resource-id'>
                      {t('loginUi.targetModes.resourceId')}
                    </option>
                    <option value='description'>
                      {t('loginUi.targetModes.description')}
                    </option>
                    <option value='text'>
                      {t('loginUi.targetModes.text')}
                    </option>
                  </select>
                </F>
                <F label={t('loginUi.findFieldValue')}>
                  <Input
                    className='h-9 text-xs'
                    value={targetValue}
                    placeholder={t(`loginUi.placeholders.${fieldName}`)}
                    onChange={(e) =>
                      patchTargetValue(fieldName, targetMode, e.target.value)
                    }
                  />
                </F>
              </div>
            </div>
          );
        })}
      </div>

      <div className='space-y-3 rounded-lg border border-border/60 bg-background/70 p-3'>
        <div>
          <div className='text-xs font-semibold'>
            {t('loginUi.submitTitle')}
          </div>
          <p className='mt-1 text-[11px] leading-relaxed text-muted-foreground'>
            {t('loginUi.submitDescription')}
          </p>
        </div>
        <F label={t('loginUi.submitLabel')}>
          <Input
            className='h-9 text-xs'
            value={submitText}
            placeholder={t('loginUi.submitPlaceholder')}
            onChange={(e) =>
              commit(
                update,
                patchLoginRecipe(step, {
                  submit: {
                    ...(recipe.submit ?? {}),
                    tap_text_any: csvToList(e.target.value)
                  }
                })
              )
            }
          />
        </F>
        <StepPanelToggle
          label={t('fields.clearFirst')}
          description={t('loginUi.clearFirstDescription')}
          checked={step.clear_first ?? true}
          onCheckedChange={(checked) => update({ clear_first: checked })}
        />
      </div>

      {POST_SUBMIT_LOGIN_FIELD_NAMES.map((fieldName) => {
        const field = recipe.post_submit_fields?.[fieldName];
        const locator = field?.locator
          ? profile.semantic_locators?.[field.locator]
          : undefined;
        const candidate = firstCandidate(locator);
        const targetMode =
          candidate.description_contains != null ||
          candidate.by === 'description'
            ? 'description'
            : candidate.by === 'text'
              ? 'text'
              : 'resource-id';
        const targetValue =
          targetMode === 'description'
            ? (candidate.description_contains ??
              (candidate.by === 'description' ? candidate.value : '') ??
              '')
            : targetMode === 'text'
              ? (candidate.value ?? '')
              : (candidate.resource_id_contains ??
                (candidate.by === 'resource-id' ? candidate.value : '') ??
                '');
        const fieldReady = Boolean(field?.value_from && targetValue);
        const defaultValueFrom = LOGIN_FIELD_DEFAULT_VALUE_FROM[fieldName];
        const selectedValueFrom = field?.value_from ?? defaultValueFrom;
        const quickPickRefs = [
          ...LOGIN_FIELD_VALUE_REF_QUICK_PICKS[fieldName],
          ...availableVariables.map((name) => `variables.${name}`)
        ];

        return (
          <div
            key={fieldName}
            className='space-y-3 rounded-lg border border-dashed border-border/70 bg-background/70 p-3'
          >
            <div className='flex items-start justify-between gap-2'>
              <div>
                <div className='text-xs font-semibold'>
                  {t('loginUi.authCodeTitle')}
                </div>
                <p className='mt-1 text-[11px] leading-relaxed text-muted-foreground'>
                  {t('loginUi.authCodeDescription')}
                </p>
              </div>
              <span
                className={`shrink-0 text-[10px] font-medium ${
                  fieldReady ? 'text-emerald-600' : 'text-muted-foreground'
                }`}
              >
                {fieldReady
                  ? t('loginUi.fieldReady')
                  : t('loginUi.optionalField')}
              </span>
            </div>

            <F label={t('loginUi.valueSource')}>
              <select
                className='h-9 w-full rounded-md border border-input bg-background px-2 text-xs'
                value={selectedValueFrom}
                onChange={(e) =>
                  commit(
                    update,
                    patchPostSubmitLoginField(step, fieldName, {
                      value_from: e.target.value,
                      required: false
                    })
                  )
                }
              >
                <option value='account.totp_code'>
                  {t('loginUi.sources.accountTotpCode')}
                </option>
                <option value='variables.auth_code'>
                  {t('loginUi.sources.authCodeVariable')}
                </option>
                <option value='scenario.auth_code'>
                  {t('loginUi.sources.authCodeScenario')}
                </option>
                {availableVariables.map((name) => (
                  <option key={name} value={`variables.${name}`}>
                    {t('loginUi.sources.variable', { name })}
                  </option>
                ))}
              </select>
              <ValueRefQuickPicks
                refs={quickPickRefs}
                selected={selectedValueFrom}
                t={t}
                onPick={(ref) =>
                  commit(
                    update,
                    patchPostSubmitLoginField(step, fieldName, {
                      value_from: ref,
                      required: false
                    })
                  )
                }
              />
            </F>

            <div className='grid gap-2 sm:grid-cols-[0.8fr_1.2fr]'>
              <F label={t('loginUi.findFieldBy')}>
                <select
                  className='h-9 w-full rounded-md border border-input bg-background px-2 text-xs'
                  value={targetMode}
                  onChange={(e) =>
                    patchTargetValue(
                      fieldName,
                      e.target.value as 'resource-id' | 'description' | 'text',
                      targetValue
                    )
                  }
                >
                  <option value='resource-id'>
                    {t('loginUi.targetModes.resourceId')}
                  </option>
                  <option value='description'>
                    {t('loginUi.targetModes.description')}
                  </option>
                  <option value='text'>{t('loginUi.targetModes.text')}</option>
                </select>
              </F>
              <F label={t('loginUi.findFieldValue')}>
                <Input
                  className='h-9 text-xs'
                  value={targetValue}
                  placeholder={t(`loginUi.placeholders.${fieldName}`)}
                  onChange={(e) =>
                    patchTargetValue(fieldName, targetMode, e.target.value)
                  }
                />
              </F>
            </div>

            <F label={t('loginUi.authCodeSubmitLabel')}>
              <Input
                className='h-9 text-xs'
                value={postSubmitText}
                placeholder={t('loginUi.authCodeSubmitPlaceholder')}
                onChange={(e) =>
                  commit(
                    update,
                    patchLoginRecipe(step, {
                      post_submit: {
                        tap_text_any: csvToList(e.target.value)
                      }
                    })
                  )
                }
              />
            </F>
          </div>
        );
      })}

      <div className='space-y-3 rounded-lg border border-dashed border-border/70 bg-background/70 p-3'>
        <div className='flex items-start justify-between gap-3'>
          <div>
            <div className='text-xs font-semibold'>
              {t('loginUi.manualChallengesTitle')}
            </div>
            <p className='mt-1 text-[11px] leading-relaxed text-muted-foreground'>
              {t('loginUi.manualChallengesDescription')}
            </p>
          </div>
          <Button
            type='button'
            size='sm'
            variant='outline'
            className='h-8 shrink-0 gap-1.5 text-xs'
            onClick={() => commit(update, addManualLoginChallenge(step))}
          >
            <Plus size={14} />
            {t('loginUi.addManualChallenge')}
          </Button>
        </div>

        {manualChallenges.length === 0 ? (
          <p className='text-[11px] text-muted-foreground'>
            {t('loginUi.noManualChallenges')}
          </p>
        ) : (
          manualChallenges.map((challenge, challengeIndex) => (
            <div
              key={`${challenge.name ?? 'challenge'}-${challengeIndex}`}
              className='space-y-3 rounded-md border border-border/60 bg-muted/20 p-3'
            >
              <div className='grid gap-2 sm:grid-cols-[1fr_1fr_auto]'>
                <F label={t('loginUi.challengeName')}>
                  <Input
                    className='h-8 font-mono text-xs'
                    value={challenge.name ?? ''}
                    onChange={(event) =>
                      commit(
                        update,
                        patchManualLoginChallenge(step, challengeIndex, {
                          name: event.target.value
                        })
                      )
                    }
                  />
                </F>
                <F label={t('loginUi.challengeKind')}>
                  <Input
                    className='h-8 font-mono text-xs'
                    value={challenge.kind ?? 'text'}
                    onChange={(event) =>
                      commit(
                        update,
                        patchManualLoginChallenge(step, challengeIndex, {
                          kind: event.target.value
                        })
                      )
                    }
                  />
                </F>
                <Button
                  type='button'
                  size='icon'
                  variant='ghost'
                  className='mt-5 size-8 text-destructive'
                  aria-label={t('loginUi.removeManualChallenge')}
                  onClick={() =>
                    commit(
                      update,
                      removeManualLoginChallenge(step, challengeIndex)
                    )
                  }
                >
                  <Trash2 size={14} />
                </Button>
              </div>

              <F label={t('loginUi.challengePrompt')}>
                <Input
                  className='h-8 text-xs'
                  value={challenge.prompt ?? ''}
                  placeholder={t('loginUi.challengePromptPlaceholder')}
                  onChange={(event) =>
                    commit(
                      update,
                      patchManualLoginChallenge(step, challengeIndex, {
                        prompt: event.target.value
                      })
                    )
                  }
                />
              </F>

              <div className='grid gap-2 sm:grid-cols-3'>
                {(
                  [
                    ['detect_locator', 'challengeDetectLocator'],
                    ['input_locator', 'challengeInputLocator'],
                    ['submit_locator', 'challengeSubmitLocator']
                  ] as const
                ).map(([field, label]) => (
                  <F key={field} label={t(`loginUi.${label}`)}>
                    <select
                      className='h-8 w-full rounded-md border border-input bg-background px-2 font-mono text-xs'
                      value={challenge[field] ?? ''}
                      onChange={(event) =>
                        commit(
                          update,
                          patchManualLoginChallenge(step, challengeIndex, {
                            [field]: event.target.value
                          })
                        )
                      }
                    >
                      <option value=''>{t('loginUi.chooseLocator')}</option>
                      {challengeLocators.map((name) => (
                        <option key={name} value={name}>
                          {name}
                        </option>
                      ))}
                    </select>
                  </F>
                ))}
              </div>

              <div className='grid gap-2 sm:grid-cols-2'>
                <F label={t('loginUi.challengeMaxAttempts')}>
                  <Input
                    type='number'
                    min={1}
                    max={10}
                    className='h-8 text-xs'
                    value={challenge.max_attempts ?? 3}
                    onChange={(event) =>
                      commit(
                        update,
                        patchManualLoginChallenge(step, challengeIndex, {
                          max_attempts: Number(event.target.value || 1)
                        })
                      )
                    }
                  />
                </F>
                <F label={t('loginUi.challengeWaitAfter')}>
                  <Input
                    type='number'
                    min={0}
                    max={10}
                    step={0.1}
                    className='h-8 text-xs'
                    value={challenge.wait_after_s ?? 0.5}
                    onChange={(event) =>
                      commit(
                        update,
                        patchManualLoginChallenge(step, challengeIndex, {
                          wait_after_s: Number(event.target.value || 0)
                        })
                      )
                    }
                  />
                </F>
              </div>
            </div>
          ))
        )}
      </div>

      <div className='rounded-lg border border-dashed border-border/70 bg-muted/20 px-3 py-2.5'>
        <div className='text-[10px] font-semibold uppercase tracking-wide text-muted-foreground'>
          {t('loginUi.summaryTitle')}
        </div>
        <p className='mt-1 text-[11px] leading-relaxed text-foreground'>
          {t('loginUi.summary', {
            loggedIn: loggedInText || t('loginUi.summaryLoggedInFallback'),
            submit: submitText || t('loginUi.summarySubmitFallback')
          })}
        </p>
      </div>

      <details className='group rounded-lg border border-border/60 bg-muted/10'>
        <summary className='flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-2.5 text-xs font-semibold'>
          <span>{t('loginUi.advancedTitle')}</span>
          <ChevronDown className='size-4 text-muted-foreground transition-transform group-open:rotate-180' />
        </summary>
        <div className='space-y-4 border-t border-border/60 p-3'>
          <StepPanelHint>{t('loginUi.advancedDescription')}</StepPanelHint>
          <LocatorEditor step={step} update={update} t={t} />
          <WatcherEditor step={step} update={update} t={t} />
        </div>
      </details>
    </div>
  );
}

function FormEditor({
  step,
  update,
  availableVariables,
  t
}: Props & { t: AppAutomationT }) {
  const profile = appAutomationProfile(step);
  const recipeName = String(step.recipe || 'basic');
  const recipe = ensureFormRecipe(profile, recipeName);
  const fields = recipe.fields ?? {};
  const fieldNames = Object.keys(fields).sort((a, b) => a.localeCompare(b));
  return (
    <MiniSection title={t('sections.formRecipe')}>
      <div className='grid gap-2 sm:grid-cols-2'>
        <F label={t('fields.recipe')}>
          <Input
            className='h-8 font-mono text-xs'
            value={recipeName}
            onChange={(e) => {
              const nextName = e.target.value.trim() || 'basic';
              commit(update, patchFormRecipe(step, nextName, recipe));
            }}
          />
        </F>
        <F label={t('fields.mode')}>
          <select
            className='h-8 w-full rounded-md border border-input bg-background px-2 text-xs'
            value={recipe.mode ?? 'strict'}
            onChange={(e) =>
              commit(
                update,
                patchFormRecipe(step, recipeName, {
                  mode: e.target.value as 'strict' | 'best_effort'
                })
              )
            }
          >
            <option value='strict'>{t('modes.strict')}</option>
            <option value='best_effort'>{t('modes.bestEffort')}</option>
          </select>
        </F>
      </div>
      <F label={t('fields.submitText')}>
        <Input
          className='h-8 text-xs'
          value={listToCsv(recipe.submit?.tap_text_any)}
          onChange={(e) =>
            commit(
              update,
              patchFormRecipe(step, recipeName, {
                submit: {
                  ...(recipe.submit ?? {}),
                  tap_text_any: csvToList(e.target.value)
                }
              })
            )
          }
        />
      </F>
      {fieldNames.map((fieldName) => (
        <div
          key={fieldName}
          className='grid gap-2 rounded-md border border-border/60 bg-background/70 p-2 sm:grid-cols-[1fr_1fr_auto]'
        >
          <F label={t('fields.field')}>
            <Input
              className='h-8 font-mono text-xs'
              value={fieldName}
              readOnly
            />
          </F>
          <F label={t('fields.locator')}>
            <select
              className='h-8 w-full rounded-md border border-input bg-background px-2 font-mono text-xs'
              value={fields[fieldName]?.locator ?? ''}
              onChange={(e) =>
                commit(
                  update,
                  patchFormField(step, recipeName, fieldName, {
                    locator: e.target.value
                  })
                )
              }
            >
              <option value=''>{t('fields.locator')}</option>
              {locatorNames(profile).map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </F>
          <Button
            type='button'
            size='icon'
            variant='ghost'
            className='mt-5 size-8'
            aria-label={t('actions.removeFormField')}
            onClick={() =>
              commit(update, removeFormField(step, recipeName, fieldName))
            }
          >
            <Trash2 size={14} />
          </Button>
          <div className='sm:col-span-3'>
            <StepPanelField label={t('fields.valueFrom')}>
              <ValueRefSelect
                value={fields[fieldName]?.value_from ?? ''}
                availableVariables={availableVariables}
                t={t}
                onChange={(value_from) =>
                  commit(
                    update,
                    patchFormField(step, recipeName, fieldName, { value_from })
                  )
                }
              />
            </StepPanelField>
          </div>
          <div className='sm:col-span-3'>
            <StepPanelToggle
              label={t('fields.required')}
              checked={fields[fieldName]?.required !== false}
              onCheckedChange={(required) =>
                commit(
                  update,
                  patchFormField(step, recipeName, fieldName, { required })
                )
              }
            />
          </div>
        </div>
      ))}
      <Button
        type='button'
        size='sm'
        variant='outline'
        className='h-8 gap-1.5 text-xs'
        onClick={() => {
          const nextName = `field_${fieldNames.length + 1}`;
          commit(
            update,
            patchFormField(step, recipeName, nextName, {
              locator: locatorNames(profile)[0] ?? '',
              value_from: 'variables.value'
            })
          );
        }}
      >
        <Plus size={14} />
        {t('actions.addField')}
      </Button>
      <StepPanelToggle
        label={t('fields.clearFirst')}
        checked={step.clear_first ?? true}
        onCheckedChange={(checked) => update({ clear_first: checked })}
      />
    </MiniSection>
  );
}

function AssertEditor({ step, update, t }: Props & { t: AppAutomationT }) {
  const profile = appAutomationProfile(step);
  return (
    <MiniSection title={t('sections.assertState')}>
      <F label={t('fields.package')}>
        <Input
          className='h-8 font-mono text-xs'
          value={step.package ?? profile.package ?? ''}
          onChange={(e) =>
            update({
              package: e.target.value,
              profile: {
                ...profile,
                package: e.target.value
              }
            })
          }
        />
      </F>
      <div className='grid gap-2 sm:grid-cols-3'>
        <F label={t('fields.anyText')}>
          <Input
            className='h-8 text-xs'
            value={listToCsv(step.any_text)}
            onChange={(e) => update({ any_text: csvToList(e.target.value) })}
          />
        </F>
        <F label={t('fields.allText')}>
          <Input
            className='h-8 text-xs'
            value={listToCsv(step.all_text)}
            onChange={(e) => update({ all_text: csvToList(e.target.value) })}
          />
        </F>
        <F label={t('fields.notText')}>
          <Input
            className='h-8 text-xs'
            value={listToCsv(step.not_text)}
            onChange={(e) => update({ not_text: csvToList(e.target.value) })}
          />
        </F>
      </div>
      <F label={t('fields.locator')}>
        <select
          className='h-8 w-full rounded-md border border-input bg-background px-2 font-mono text-xs'
          value={step.locator ?? ''}
          onChange={(e) => update({ locator: e.target.value })}
        >
          <option value=''>{t('options.none')}</option>
          {locatorNames(profile).map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </F>
    </MiniSection>
  );
}

function WatcherEditor({ step, update, t }: Props & { t: AppAutomationT }) {
  const profile = appAutomationProfile(step);
  const watchers = profile.popup_watchers ?? [];
  return (
    <MiniSection title={t('sections.watchers')}>
      <StepPanelToggle
        label={t('fields.runWatchers')}
        checked={step.app_popup_watchers_enabled !== false}
        onCheckedChange={(checked) =>
          update({ app_popup_watchers_enabled: checked })
        }
      />
      {watchers.map((watcher, index) => (
        <div
          key={`${watcher.name ?? 'watcher'}-${index}`}
          className='space-y-2 rounded-md border border-border/60 bg-background/70 p-2'
        >
          <div className='flex min-w-0 items-center gap-2'>
            <Input
              className='h-8 min-w-0 flex-1 font-mono text-xs'
              value={watcher.name ?? ''}
              onChange={(e) =>
                commit(
                  update,
                  patchPopupWatcher(step, index, { name: e.target.value })
                )
              }
            />
            <Button
              type='button'
              size='icon'
              variant='ghost'
              className='size-8 shrink-0'
              aria-label={t('actions.removeWatcher')}
              onClick={() => commit(update, removePopupWatcher(step, index))}
            >
              <Trash2 size={14} />
            </Button>
          </div>
          <div className='grid gap-2 sm:grid-cols-2'>
            <F label={t('fields.whenTextContains')}>
              <Input
                className='h-8 text-xs'
                value={listToCsv(watcher.when?.text_contains)}
                onChange={(e) =>
                  commit(
                    update,
                    patchPopupWatcher(step, index, {
                      when: {
                        ...(watcher.when ?? {}),
                        text_contains: csvToList(e.target.value)
                      }
                    })
                  )
                }
              />
            </F>
            <F label={t('fields.tapTextAny')}>
              <Input
                className='h-8 text-xs'
                value={listToCsv(watcher.action?.tap_text_any)}
                onChange={(e) =>
                  commit(
                    update,
                    patchPopupWatcher(step, index, {
                      action: {
                        ...(watcher.action ?? {}),
                        tap_text_any: csvToList(e.target.value)
                      }
                    })
                  )
                }
              />
            </F>
          </div>
          <div className='grid gap-2 sm:grid-cols-2'>
            <F label={t('fields.maxTriggers')}>
              <Input
                type='number'
                min={1}
                max={20}
                className='h-8 text-xs'
                value={watcher.max_triggers_per_run ?? 3}
                onChange={(e) =>
                  commit(
                    update,
                    patchPopupWatcher(step, index, {
                      max_triggers_per_run: Number(e.target.value) || 1
                    })
                  )
                }
              />
            </F>
            <F label={t('fields.cooldownMs')}>
              <Input
                type='number'
                min={0}
                step={100}
                className='h-8 text-xs'
                value={watcher.cooldown_ms ?? 2000}
                onChange={(e) =>
                  commit(
                    update,
                    patchPopupWatcher(step, index, {
                      cooldown_ms: Number(e.target.value) || 0
                    })
                  )
                }
              />
            </F>
          </div>
          <div className='grid gap-2 sm:grid-cols-2'>
            <StepPanelToggle
              label={t('fields.enabled')}
              checked={watcher.enabled !== false}
              onCheckedChange={(enabled) =>
                commit(update, patchPopupWatcher(step, index, { enabled }))
              }
            />
            <StepPanelToggle
              label={t('fields.allowUnsafe')}
              checked={Boolean(watcher.action?.allow_unsafe)}
              onCheckedChange={(allow_unsafe) =>
                commit(
                  update,
                  patchPopupWatcher(step, index, {
                    action: {
                      ...(watcher.action ?? {}),
                      allow_unsafe
                    }
                  })
                )
              }
            />
          </div>
        </div>
      ))}
      <Button
        type='button'
        size='sm'
        variant='outline'
        className='h-8 gap-1.5 text-xs'
        onClick={() => commit(update, addPopupWatcher(step))}
      >
        <Plus size={14} />
        {t('actions.addWatcher')}
      </Button>
    </MiniSection>
  );
}

export function AppAutomationStepFields({
  step,
  update,
  availableVariables = []
}: Props) {
  const t = useTranslations('campaignsFeature.stepEditor.appAutomation');
  const profile = appAutomationProfile(step);
  if (step.type === 'login_if_needed') {
    return (
      <LoginEditor
        step={step}
        update={update}
        availableVariables={availableVariables}
        t={t}
      />
    );
  }
  return (
    <div className='space-y-4'>
      <MiniSection title={t('sections.profile')}>
        <F label={t('fields.package')}>
          <Input
            className='h-8 font-mono text-xs'
            value={profile.package ?? ''}
            onChange={(e) =>
              commit(update, patchProfile(step, { package: e.target.value }))
            }
          />
        </F>
      </MiniSection>
      <LocatorEditor step={step} update={update} t={t} />
      {step.type === 'fill_form' ? (
        <FormEditor
          step={step}
          update={update}
          availableVariables={availableVariables}
          t={t}
        />
      ) : null}
      {step.type === 'assert_app_state' ? (
        <AssertEditor step={step} update={update} t={t} />
      ) : null}
      <WatcherEditor step={step} update={update} t={t} />
    </div>
  );
}
