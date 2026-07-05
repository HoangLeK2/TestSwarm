'use client';

import type { ReactNode } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { FlowStep } from '../scenario-steps/types';
import {
  addLocator,
  addPopupWatcher,
  appAutomationProfile,
  csvToList,
  ensureFormRecipe,
  ensureLoginRecipe,
  firstCandidate,
  listToCsv,
  locatorNames,
  patchFormField,
  patchFormRecipe,
  patchLocator,
  patchLoginField,
  patchLoginRecipe,
  patchPopupWatcher,
  patchProfile,
  removeFormField,
  removeLocator,
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

const LOGIN_FIELD_LABEL_KEYS = {
  username: 'loginFields.username',
  password: 'loginFields.password'
} as const;

function commit(update: Props['update'], next: FlowStep) {
  update(next as Partial<FlowStep>);
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
    'secret.login_password',
    'scenario.username',
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
  availableVariables,
  t
}: Props & { t: AppAutomationT }) {
  const profile = appAutomationProfile(step);
  const recipe = ensureLoginRecipe(profile);
  const fields = recipe.fields ?? {};
  return (
    <MiniSection title={t('sections.loginRecipe')}>
      <div className='grid gap-2 sm:grid-cols-2'>
        <F label={t('fields.loggedInText')}>
          <Input
            className='h-8 text-xs'
            value={listToCsv(recipe.detect_logged_in?.any_text)}
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
        <F label={t('fields.submitText')}>
          <Input
            className='h-8 text-xs'
            value={listToCsv(recipe.submit?.tap_text_any)}
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
      </div>
      {LOGIN_FIELD_NAMES.map((fieldName) => (
        <div
          key={fieldName}
          className='grid gap-2 rounded-md border border-border/60 bg-background/70 p-2 sm:grid-cols-2'
        >
          <F
            label={t('fields.loginLocator', {
              field: t(LOGIN_FIELD_LABEL_KEYS[fieldName])
            })}
          >
            <select
              className='h-8 w-full rounded-md border border-input bg-background px-2 font-mono text-xs'
              value={fields[fieldName]?.locator ?? ''}
              onChange={(e) =>
                commit(
                  update,
                  patchLoginField(step, fieldName, {
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
          <F
            label={t('fields.loginValueFrom', {
              field: t(LOGIN_FIELD_LABEL_KEYS[fieldName])
            })}
          >
            <ValueRefSelect
              value={fields[fieldName]?.value_from ?? ''}
              availableVariables={availableVariables}
              t={t}
              onChange={(value_from) =>
                commit(update, patchLoginField(step, fieldName, { value_from }))
              }
            />
          </F>
        </div>
      ))}
      <StepPanelToggle
        label={t('fields.clearFirst')}
        checked={step.clear_first ?? true}
        onCheckedChange={(checked) => update({ clear_first: checked })}
      />
    </MiniSection>
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
      {step.type === 'login_if_needed' ? (
        <LoginEditor
          step={step}
          update={update}
          availableVariables={availableVariables}
          t={t}
        />
      ) : null}
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
