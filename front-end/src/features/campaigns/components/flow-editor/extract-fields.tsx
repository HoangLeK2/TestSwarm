'use client';

import { useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { VariableInsertMenu } from '@/components/variable-insert-menu';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { FlowStep } from '../scenario-steps/types';
import { SCENARIO_VAR_TOKENS } from '../../i18n/scenario-var-tokens';
import {
  F,
  StepPanelField,
  StepPanelHint,
  StepPanelSection,
  StepPanelToggle
} from './step-panel-primitives';
import { parentPostIdVarForMode } from './extract-parent-mode';
import { PlatformSelect } from './platform-select';

type ExtractStep = FlowStep & {
  entity?: string;
  edge_extra_data?: boolean;
  entity_version?: string;
  extract_profile?: string;
  open_post_before_extract?: boolean;
  open_post_press_back_after_extract?: boolean;
  expand_see_more?: boolean;
  stop_if_no_new?: boolean;
  expand_see_more_max_passes?: number | string;
  expand_see_more_scroll?: boolean;
  expand_see_more_scroll_distance?: number | string;
  expand_lazy_hydration_rounds?: number | string;
  expand_lazy_scroll_distance?: number | string;
  expand_prefetch_scroll_passes?: number | string;
  expand_prefetch_scroll_pause?: number | string;
  expand_completion_retries?: number | string;
  max_pages?: number | string;
  max_items?: number | string;
  entity_scroll_pause_s?: number | string;
  parent_post_id_var?: string;
  comment_scroll_passes?: number | string;
  comment_swipes_per_dump?: number | string;
  comment_scroll_distance?: number | string;
  comment_scroll_duration_ms?: number | string;
  comment_scroll_pause_s?: number | string;
  comment_scroll_wall_s?: number | string;
  comment_require_complete?: boolean;
  comment_auto_coverage_target_max?: number | string;
  allow_partial_comments?: boolean;
  comment_no_growth_break?: number | string;
  min_comment_scan_passes?: number | string;
  comment_max_snapshots?: number | string;
  comment_stop_if_no_new?: boolean;
  no_new_threshold?: number | string;
  result_var?: string;
  collection?: string;
  platform?: string;
  content_type?: string;
  dedupe_field?: string;
  tags?: string;
  save_parent_id_var?: string;
  item_level?: number;
};

const EXTRACT_PROFILES = ['balanced', 'aggressive', 'safe'] as const;

const STRATEGIES = [
  {
    value: 'posts',
    titleKey: 'strategyPostsTitle',
    descKey: 'strategyPostsDesc'
  },
  {
    value: 'comments',
    titleKey: 'strategyCommentsTitle',
    descKey: 'strategyCommentsDesc'
  },
  {
    value: 'groups',
    titleKey: 'strategyGroupsTitle',
    descKey: 'strategyGroupsDesc'
  },
  {
    value: 'text_nodes',
    titleKey: 'strategyTextTitle',
    descKey: 'strategyTextDesc'
  }
] as const;

const FLOW_STEPS = [
  'flowRead',
  'flowExpand',
  'flowScroll',
  'flowSave'
] as const;

function isVarRef(v: string) {
  return /^\$\{[^}]+\}$/.test(v.trim());
}

function parseNumOrVar(raw: string, fallback: number): number | string {
  const v = raw.trim();
  if (!v) return fallback;
  if (isVarRef(v)) return v;
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function insertToken(raw: string, token: string): string {
  const current = raw ?? '';
  if (!current.trim()) return token;
  const matches = current.match(/\$\{[^}]+\}/g);
  if (matches?.includes(token)) return current;
  return `${current} ${token}`.trim();
}

function VariableValueInput({
  availableVariables,
  value,
  onValueChange,
  placeholder,
  insertMode = 'replace'
}: {
  availableVariables: string[];
  value: string;
  onValueChange: (value: string) => void;
  placeholder?: string;
  insertMode?: 'append' | 'replace';
}) {
  const tStep = useTranslations('campaignsFeature.stepEditor');

  return (
    <div className='space-y-1.5'>
      <Input
        className='h-8 font-mono text-xs'
        value={value}
        placeholder={placeholder}
        onChange={(event) => onValueChange(event.target.value)}
      />
      {availableVariables.length > 0 ? (
        <VariableInsertMenu
          groups={[
            {
              label: tStep('variableInsert.availableVariables'),
              items: availableVariables.map((name) => {
                const token = `\${${name}}`;
                return { value: token };
              })
            }
          ]}
          label={tStep('variableInsert.placeholder')}
          onInsert={(token) =>
            onValueChange(
              insertMode === 'replace' ? token : insertToken(value, token)
            )
          }
          fullWidth
          align='start'
        />
      ) : null}
    </div>
  );
}

function StrategyCard({
  title,
  description,
  selected,
  onSelect,
  selectedLabel
}: {
  title: string;
  description: string;
  selected: boolean;
  selectedLabel: string;
  onSelect: () => void;
}) {
  return (
    <button
      type='button'
      onClick={onSelect}
      className={cn(
        'flex min-w-0 flex-1 flex-col gap-1 rounded-lg border px-2.5 py-2 text-left transition-colors',
        selected
          ? 'border-primary/40 bg-primary/[0.06] ring-1 ring-primary/20'
          : 'border-border/60 bg-background/90 hover:bg-muted/30'
      )}
    >
      <span className='text-xs font-semibold leading-snug text-foreground'>
        {title}
      </span>
      <span className='text-[10px] leading-relaxed text-muted-foreground'>
        {description}
      </span>
      {selected ? (
        <Badge
          variant='secondary'
          className='mt-0.5 w-fit px-1.5 py-0 text-[9px]'
        >
          {selectedLabel}
        </Badge>
      ) : null}
    </button>
  );
}

function FlowStrip({
  labels
}: {
  labels: readonly [string, string, string, string];
}) {
  return (
    <div className='flex items-center gap-1 rounded-lg bg-muted/40 px-2 py-2'>
      {labels.map((label, i) => (
        <div key={label} className='flex min-w-0 flex-1 items-center'>
          <span className='w-full truncate text-center text-[10px] font-medium text-muted-foreground'>
            {label}
          </span>
          {i < labels.length - 1 ? (
            <span className='shrink-0 px-0.5 text-[10px] text-muted-foreground/70'>
              →
            </span>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function CompactField({
  label,
  hint,
  children
}: {
  label: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className='space-y-1 rounded-md border border-border/50 bg-background/80 p-2'>
      <span className='text-[10px] font-medium text-muted-foreground'>
        {label}
      </span>
      {children}
      {hint ? (
        <p className='text-[9px] leading-relaxed text-muted-foreground/90'>
          {hint}
        </p>
      ) : null}
    </div>
  );
}

const ACTIVE_SAVE_PARENT_VAR = '_active_comment_parent_hash';

function saveDefaultsForEntity(entity: string): {
  content_type: string;
  dedupe_field: string;
} {
  if (entity === 'comments') {
    return { content_type: 'comment', dedupe_field: 'comment_key' };
  }
  if (entity === 'posts') {
    return { content_type: 'post', dedupe_field: 'post_key' };
  }
  return { content_type: 'text', dedupe_field: 'text' };
}

/** Switch extract strategy and drop fields that do not apply (update() cannot delete keys). */
function applyExtractEntitySwitch(
  step: ExtractStep,
  entity: string,
  saveEnabled: boolean
): ExtractStep {
  const next: ExtractStep = { ...step, entity };

  if (entity === 'posts') {
    next.edge_extra_data = step.edge_extra_data ?? true;
    next.entity_version = 'posts:v1';
    next.open_post_before_extract = true;
    next.open_post_press_back_after_extract = false;
    next.extract_profile = step.extract_profile ?? 'balanced';
  } else if (entity === 'comments') {
    next.edge_extra_data = step.edge_extra_data ?? true;
    next.entity_version = 'comments:v1';
    next.extract_profile = step.extract_profile ?? 'balanced';
    next.open_post_press_back_after_extract =
      step.open_post_press_back_after_extract ?? true;
    delete next.open_post_before_extract;
  } else if (entity === 'groups') {
    next.edge_extra_data = step.edge_extra_data ?? true;
    next.entity_version = 'groups:v1';
    next.max_pages = step.max_pages ?? '${MAX_PAGES}';
    next.max_items = step.max_items ?? 500;
    next.stop_if_no_new = step.stop_if_no_new ?? true;
    next.no_new_threshold = step.no_new_threshold ?? 2;
    next.entity_scroll_pause_s = step.entity_scroll_pause_s ?? 0.6;
    delete next.open_post_before_extract;
    delete next.open_post_press_back_after_extract;
    delete next.extract_profile;
    delete next.parent_post_id_var;
    delete next.comment_scroll_passes;
    delete next.comment_swipes_per_dump;
    delete next.comment_scroll_distance;
    delete next.comment_scroll_duration_ms;
    delete next.comment_scroll_pause_s;
    delete next.comment_scroll_wall_s;
    delete next.comment_no_growth_break;
    delete next.min_comment_scan_passes;
    delete next.comment_max_snapshots;
    delete next.comment_stop_if_no_new;
  } else if (entity === 'text_nodes') {
    next.edge_extra_data = step.edge_extra_data ?? true;
    next.entity_version = 'text_nodes:v1';
    delete next.open_post_before_extract;
    delete next.open_post_press_back_after_extract;
    delete next.extract_profile;
    delete next.parent_post_id_var;
    delete next.comment_scroll_passes;
    delete next.comment_swipes_per_dump;
    delete next.comment_scroll_distance;
    delete next.comment_scroll_duration_ms;
    delete next.comment_scroll_pause_s;
    delete next.comment_scroll_wall_s;
    delete next.comment_no_growth_break;
    delete next.min_comment_scan_passes;
    delete next.comment_max_snapshots;
    delete next.comment_stop_if_no_new;
  }

  if (saveEnabled) {
    Object.assign(next, saveDefaultsForEntity(entity));
    if (entity !== 'comments') {
      delete next.save_parent_id_var;
    }
    next.platform = entity === 'text_nodes' ? 'ui' : (step.platform ?? 'auto');
  }

  return next;
}

function labelPlatform(platform: string | undefined, t: (k: string) => string) {
  if (!platform || platform === 'auto') return t('savePlatformAuto');
  if (platform === 'ui') return t('savePlatformUi');
  return platform;
}

function labelContentType(
  contentType: string | undefined,
  entity: string,
  t: (k: string) => string
) {
  const ct = contentType ?? saveDefaultsForEntity(entity).content_type;
  if (ct === 'comment') return t('saveContentTypeGenericComment');
  if (ct === 'post') return t('saveContentTypeGenericPost');
  if (ct === 'text') return t('saveContentTypeText');
  return ct;
}

function labelCollection(
  collection: string | undefined,
  t: (k: string, values?: { name: string }) => string
) {
  const c = collection?.trim();
  if (!c) return '—';
  if (c === '${SAVE_COLLECTION}') return t('saveCollectionCampaignVar');
  const m = c.match(/^\$\{([^}]+)\}$/);
  if (m) return t('saveCollectionVar', { name: m[1] });
  return c;
}

function labelDedupe(
  field: string | undefined,
  entity: string,
  t: (k: string) => string
) {
  const d = field ?? saveDefaultsForEntity(entity).dedupe_field;
  if (d === 'comment_key') return t('saveDedupeCommentKey');
  if (d === 'post_key') return t('saveDedupePostKey');
  if (d === 'text') return t('saveDedupeText');
  return d;
}

function SaveSummaryCard({
  title,
  rows
}: {
  title: string;
  rows: { label: string; value: string }[];
}) {
  return (
    <div className='rounded-lg border border-primary/15 bg-primary/[0.04] px-3 py-2.5'>
      <p className='mb-2 text-[11px] font-semibold text-foreground'>{title}</p>
      <dl className='grid gap-1.5'>
        {rows.map(({ label, value }) => (
          <div
            key={label}
            className='flex items-baseline justify-between gap-3 text-[11px]'
          >
            <dt className='shrink-0 text-muted-foreground'>{label}</dt>
            <dd className='min-w-0 text-right font-medium text-foreground'>
              {value}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function CollapsibleBlock({
  title,
  badge,
  defaultOpen = false,
  children
}: {
  title: string;
  badge?: React.ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className='rounded-lg border border-dashed border-border/70'>
      <button
        type='button'
        className='flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left'
        onClick={() => setOpen((v) => !v)}
      >
        <span className='text-xs font-medium text-foreground'>{title}</span>
        <span className='flex items-center gap-1.5'>
          {badge}
          <ChevronDown
            size={14}
            className={cn(
              'shrink-0 text-muted-foreground transition-transform',
              open && 'rotate-180'
            )}
          />
        </span>
      </button>
      {open ? (
        <div className='space-y-3 border-t border-border/60 px-3 pb-3 pt-2'>
          {children}
        </div>
      ) : null}
    </div>
  );
}

export function ExtractStepFields({
  step,
  update,
  onChange,
  view = 'all',
  availableVariables = []
}: {
  step: ExtractStep;
  update: (fields: Partial<FlowStep>) => void;
  onChange: (step: FlowStep) => void;
  view?: 'all' | 'screen' | 'data-save';
  availableVariables?: string[];
}) {
  const t = useTranslations('campaignsFeature.stepEditor.extract');
  const tPlatform = useTranslations(
    'campaignsFeature.stepEditor.platformSelect'
  );
  const entity = step.entity ?? 'posts';
  const expand = step.expand_see_more ?? true;
  const openPost =
    step.open_post_before_extract ?? (entity === 'posts' ? true : false);
  const autoBackAfterOpenPost =
    step.open_post_press_back_after_extract ?? false;
  const extractParentMode = step.parent_post_id_var ? 'custom' : 'auto';
  const saveEnabled = !!step.collection;
  const saveParentMode =
    !step.save_parent_id_var ||
    step.save_parent_id_var === ACTIVE_SAVE_PARENT_VAR
      ? 'auto'
      : 'custom';

  const flowLabels = FLOW_STEPS.map((k) => t(k)) as [
    string,
    string,
    string,
    string
  ];

  const saveSummaryRows = [
    {
      label: t('saveSummaryPlatform'),
      value: labelPlatform(step.platform, t)
    },
    {
      label: t('saveSummaryContentType'),
      value: labelContentType(step.content_type, entity, t)
    },
    {
      label: t('saveSummaryStorage'),
      value: labelCollection(step.collection, t)
    },
    {
      label: t('saveSummaryDedupe'),
      value: labelDedupe(step.dedupe_field, entity, t)
    }
  ];

  const dedupeOptions =
    entity === 'comments'
      ? (['comment_key', 'text'] as const)
      : entity === 'posts'
        ? (['post_key', 'text'] as const)
        : (['text'] as const);
  const showScreen = view === 'all' || view === 'screen';
  const showDataSave = view === 'all' || view === 'data-save';

  return (
    <div className='space-y-3'>
      {showScreen ? <StepPanelHint>{t('intro')}</StepPanelHint> : null}

      {showScreen ? (
        <div className='space-y-3'>
          <StepPanelSection title={t('sourceSectionTitle')}>
            <div className='flex gap-2'>
              {STRATEGIES.map((s) => (
                <StrategyCard
                  key={s.value}
                  title={t(s.titleKey)}
                  description={t(s.descKey)}
                  selected={entity === s.value}
                  selectedLabel={t('strategySelected')}
                  onSelect={() =>
                    onChange(
                      applyExtractEntitySwitch(step, s.value, saveEnabled)
                    )
                  }
                />
              ))}
            </div>
            <FlowStrip labels={flowLabels} />
            <PlatformSelect
              value={step.platform}
              onChange={(platform) => onChange({ ...step, platform })}
              entity={entity}
            />
            <p className='text-[11px] leading-relaxed text-muted-foreground'>
              {tPlatform('autoHint')}
            </p>
          </StepPanelSection>

          <StepPanelSection title={t('behaviorSectionTitle')}>
            {entity === 'posts' || entity === 'comments' ? (
              <StepPanelField label={t('extractProfileLabel')}>
                <select
                  className='h-9 w-full rounded-md border border-input bg-background px-2 text-xs'
                  value={step.extract_profile ?? 'balanced'}
                  onChange={(e) => update({ extract_profile: e.target.value })}
                >
                  {EXTRACT_PROFILES.map((profile) => (
                    <option key={profile} value={profile}>
                      {t(`extractProfile_${profile}`)}
                    </option>
                  ))}
                </select>
                <p className='mt-1 text-[10px] text-muted-foreground'>
                  {t('extractProfileHint')}
                </p>
              </StepPanelField>
            ) : null}
            {entity === 'posts' ? (
              <>
                <StepPanelToggle
                  label={t('openPostBeforeExtractLabel')}
                  description={t('openPostBeforeExtractDescription')}
                  checked={openPost}
                  onCheckedChange={(checked) => {
                    const patch: Partial<FlowStep> = {
                      open_post_before_extract: checked
                    };
                    if (
                      checked &&
                      step.open_post_press_back_after_extract === undefined
                    ) {
                      patch.open_post_press_back_after_extract = false;
                    }
                    update(patch);
                  }}
                />
                {openPost ? (
                  <StepPanelToggle
                    label={t('openPostPressBackLabel')}
                    description={t('openPostPressBackDescription')}
                    checked={autoBackAfterOpenPost}
                    onCheckedChange={(checked) =>
                      update({ open_post_press_back_after_extract: checked })
                    }
                  />
                ) : null}
                {openPost && !autoBackAfterOpenPost ? (
                  <StepPanelHint>{t('openPostManualBackHint')}</StepPanelHint>
                ) : null}
              </>
            ) : null}
            {entity === 'comments' ? (
              <StepPanelToggle
                label={t('openPostPressBackLabel')}
                description={t('openPostPressBackDescription')}
                checked={autoBackAfterOpenPost}
                onCheckedChange={(checked) =>
                  update({ open_post_press_back_after_extract: checked })
                }
              />
            ) : null}
            <StepPanelToggle
              label={t('expandSeeMoreLabel')}
              description={t('expandSeeMoreDescription')}
              checked={expand}
              onCheckedChange={(checked) =>
                update({ expand_see_more: checked })
              }
            />
            {entity !== 'comments' ? (
              <StepPanelToggle
                label={t('stopIfNoNewLabel')}
                description={t('stopIfNoNewDescription')}
                checked={step.stop_if_no_new ?? false}
                onCheckedChange={(checked) =>
                  update({ stop_if_no_new: checked })
                }
              />
            ) : null}
          </StepPanelSection>

          {entity === 'posts' ||
          entity === 'comments' ||
          entity === 'groups' ||
          entity === 'text_nodes' ? (
            <StepPanelSection
              title={t('adapterExtraTitle')}
              badge={
                <Badge variant='outline' className='text-[10px] font-normal'>
                  {t('adapterExtraBadge')}
                </Badge>
              }
            >
              <StepPanelToggle
                label={t('edgeExtraDataLabel')}
                description={t('edgeExtraDataDescription')}
                checked={step.edge_extra_data !== false}
                onCheckedChange={(checked) =>
                  update({ edge_extra_data: checked })
                }
              />
              <CompactField
                label={t('strategyVersionLabel')}
                hint={t('strategyVersionHint')}
              >
                <Input
                  className='h-8 font-mono text-xs'
                  disabled
                  value={
                    step.entity_version ??
                    (entity === 'comments'
                      ? 'comments:v1'
                      : entity === 'groups'
                        ? 'groups:v1'
                        : entity === 'text_nodes'
                          ? 'text_nodes:v1'
                          : 'posts:v1')
                  }
                />
              </CompactField>

              {entity === 'groups' ? (
                <div className='space-y-3 rounded-lg border border-border/60 bg-muted/20 p-3'>
                  <div className='grid grid-cols-2 gap-3'>
                    <CompactField
                      label={t('groupMaxPagesLabel')}
                      hint={t('groupMaxPagesHint')}
                    >
                      <VariableValueInput
                        availableVariables={availableVariables}
                        value={String(step.max_pages ?? '${MAX_PAGES}')}
                        onValueChange={(value) =>
                          update({
                            max_pages: parseNumOrVar(value, 20)
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('groupMaxItemsLabel')}
                      hint={t('groupMaxItemsHint')}
                    >
                      <VariableValueInput
                        availableVariables={availableVariables}
                        value={String(step.max_items ?? 500)}
                        onValueChange={(value) =>
                          update({
                            max_items: parseNumOrVar(value, 500)
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('groupNoNewThresholdLabel')}
                      hint={t('groupNoNewThresholdHint')}
                    >
                      <VariableValueInput
                        availableVariables={availableVariables}
                        value={String(step.no_new_threshold ?? 2)}
                        onValueChange={(value) =>
                          update({
                            no_new_threshold: parseNumOrVar(value, 2)
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('groupScrollPauseLabel')}
                      hint={t('groupScrollPauseHint')}
                    >
                      <VariableValueInput
                        availableVariables={availableVariables}
                        value={String(step.entity_scroll_pause_s ?? 0.6)}
                        onValueChange={(value) =>
                          update({
                            entity_scroll_pause_s: parseNumOrVar(value, 0.6)
                          })
                        }
                      />
                    </CompactField>
                  </div>
                </div>
              ) : null}

              {entity === 'comments' ? (
                <div className='space-y-3 rounded-lg border border-border/60 bg-muted/20 p-3'>
                  <div className='grid grid-cols-2 gap-3'>
                    <CompactField
                      label={t('maxItemsLabel')}
                      hint={t('maxItemsHint')}
                    >
                      <VariableValueInput
                        availableVariables={availableVariables}
                        value={String(step.max_items ?? 220)}
                        onValueChange={(value) =>
                          update({
                            max_items: parseNumOrVar(value, 220)
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('parentPostIdVarLabel')}
                      hint={t('parentPostIdVarHint')}
                    >
                      <select
                        className='h-8 w-full rounded-md border border-input bg-background px-2 text-xs'
                        value={extractParentMode}
                        onChange={(e) =>
                          update({
                            parent_post_id_var: parentPostIdVarForMode(
                              e.target.value,
                              step.parent_post_id_var
                            )
                          })
                        }
                      >
                        <option value='auto'>{t('parentPostModeAuto')}</option>
                        <option value='custom'>
                          {t('parentPostModeCustom')}
                        </option>
                      </select>
                      {extractParentMode === 'custom' ? (
                        <Input
                          className='mt-1.5 h-8 font-mono text-xs'
                          placeholder='_comment_parent_pid'
                          value={step.parent_post_id_var ?? ''}
                          onChange={(e) =>
                            update({
                              parent_post_id_var: e.target.value || undefined
                            })
                          }
                        />
                      ) : null}
                    </CompactField>
                    <CompactField
                      label={t('commentScrollPassesLabel')}
                      hint={t('commentScrollPassesHint')}
                    >
                      <VariableValueInput
                        availableVariables={availableVariables}
                        value={String(step.comment_scroll_passes ?? 16)}
                        onValueChange={(value) =>
                          update({
                            comment_scroll_passes: parseNumOrVar(value, 16)
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('commentSwipesPerDumpLabel')}
                      hint={t('commentSwipesPerDumpHint')}
                    >
                      <VariableValueInput
                        availableVariables={availableVariables}
                        value={String(step.comment_swipes_per_dump ?? 4)}
                        onValueChange={(value) =>
                          update({
                            comment_swipes_per_dump: parseNumOrVar(value, 4)
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('commentScrollDistanceLabel')}
                      hint={t('commentScrollDistanceHint')}
                    >
                      <VariableValueInput
                        availableVariables={availableVariables}
                        value={String(step.comment_scroll_distance ?? 0.52)}
                        onValueChange={(value) =>
                          update({
                            comment_scroll_distance: parseNumOrVar(value, 0.52)
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('commentScrollDurationLabel')}
                      hint={t('commentScrollDurationHint')}
                    >
                      <VariableValueInput
                        availableVariables={availableVariables}
                        value={String(step.comment_scroll_duration_ms ?? 120)}
                        onValueChange={(value) =>
                          update({
                            comment_scroll_duration_ms: parseNumOrVar(
                              value,
                              120
                            )
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('commentScrollPauseLabel')}
                      hint={t('commentScrollPauseHint')}
                    >
                      <VariableValueInput
                        availableVariables={availableVariables}
                        value={String(step.comment_scroll_pause_s ?? 0.03)}
                        onValueChange={(value) =>
                          update({
                            comment_scroll_pause_s: parseNumOrVar(value, 0.03)
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('commentEarlyStopLabel')}
                      hint={t('commentEarlyStopHint')}
                    >
                      <select
                        className='h-8 w-full rounded-md border border-input bg-background px-2 text-xs'
                        value={
                          (step.comment_stop_if_no_new ?? step.stop_if_no_new)
                            ? 'no_new'
                            : 'off'
                        }
                        onChange={(e) => {
                          const enabled = e.target.value === 'no_new';
                          update({
                            comment_stop_if_no_new: enabled,
                            stop_if_no_new: enabled
                          });
                        }}
                      >
                        <option value='off'>{t('commentEarlyStopOff')}</option>
                        <option value='no_new'>
                          {t('commentEarlyStopNoNew')}
                        </option>
                      </select>
                    </CompactField>
                    <CompactField
                      label={t('commentNoGrowthBreakLabel')}
                      hint={t('commentNoGrowthBreakHint')}
                    >
                      <VariableValueInput
                        availableVariables={availableVariables}
                        value={String(step.comment_no_growth_break ?? 0)}
                        onValueChange={(value) =>
                          update({
                            comment_no_growth_break: parseNumOrVar(value, 0)
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('minCommentScanPassesLabel')}
                      hint={t('minCommentScanPassesHint')}
                    >
                      <VariableValueInput
                        availableVariables={availableVariables}
                        value={String(step.min_comment_scan_passes ?? 2)}
                        onValueChange={(value) =>
                          update({
                            min_comment_scan_passes: parseNumOrVar(value, 2)
                          })
                        }
                      />
                    </CompactField>
                  </div>
                </div>
              ) : null}
            </StepPanelSection>
          ) : null}

          {expand ? (
            <CollapsibleBlock
              title={t('advancedExpandTitle')}
              badge={
                <span className='text-[10px] text-muted-foreground'>
                  {t('advancedDefaultOk')}
                </span>
              }
            >
              <StepPanelHint>{t('advancedExpandHint')}</StepPanelHint>
              <div className='grid grid-cols-2 gap-2'>
                <CompactField
                  label={t('maxPassesLabel')}
                  hint={t('maxPassesHint')}
                >
                  <VariableValueInput
                    availableVariables={availableVariables}
                    value={String(step.expand_see_more_max_passes ?? 2)}
                    onValueChange={(value) =>
                      update({
                        expand_see_more_max_passes: parseNumOrVar(value, 2)
                      })
                    }
                  />
                </CompactField>
                <CompactField
                  label={t('scrollBetweenLabel')}
                  hint={t('scrollBetweenHint')}
                >
                  <select
                    className='h-8 w-full rounded-md border border-input bg-background px-2 text-xs'
                    value={String(step.expand_see_more_scroll ?? false)}
                    onChange={(e) =>
                      update({
                        expand_see_more_scroll: e.target.value === 'true'
                      })
                    }
                  >
                    <option value='false'>{t('booleanFalse')}</option>
                    <option value='true'>{t('booleanTrue')}</option>
                  </select>
                </CompactField>
                <CompactField
                  label={t('scrollDistanceLabel')}
                  hint={t('scrollDistanceHint')}
                >
                  <VariableValueInput
                    availableVariables={availableVariables}
                    value={String(step.expand_see_more_scroll_distance ?? 0.3)}
                    onValueChange={(value) =>
                      update({
                        expand_see_more_scroll_distance: parseNumOrVar(
                          value,
                          0.3
                        )
                      })
                    }
                  />
                </CompactField>
                <CompactField
                  label={t('lazyHydrationRoundsLabel')}
                  hint={t('lazyHydrationRoundsHint')}
                >
                  <VariableValueInput
                    availableVariables={availableVariables}
                    value={String(step.expand_lazy_hydration_rounds ?? 6)}
                    onValueChange={(value) =>
                      update({
                        expand_lazy_hydration_rounds: parseNumOrVar(value, 6)
                      })
                    }
                  />
                </CompactField>
                <CompactField
                  label={t('lazyHydrationScrollDistanceLabel')}
                  hint={t('lazyHydrationScrollDistanceHint')}
                >
                  <VariableValueInput
                    availableVariables={availableVariables}
                    value={String(step.expand_lazy_scroll_distance ?? 0.3)}
                    onValueChange={(value) =>
                      update({
                        expand_lazy_scroll_distance: parseNumOrVar(value, 0.3)
                      })
                    }
                  />
                </CompactField>
                <CompactField
                  label={t('prefetchScrollPassesLabel')}
                  hint={t('prefetchScrollPassesHint')}
                >
                  <VariableValueInput
                    availableVariables={availableVariables}
                    value={String(step.expand_prefetch_scroll_passes ?? 0)}
                    onValueChange={(value) =>
                      update({
                        expand_prefetch_scroll_passes: parseNumOrVar(value, 0)
                      })
                    }
                  />
                </CompactField>
                <CompactField
                  label={t('prefetchScrollPauseLabel')}
                  hint={t('prefetchScrollPauseHint')}
                >
                  <VariableValueInput
                    availableVariables={availableVariables}
                    value={String(step.expand_prefetch_scroll_pause ?? 0.7)}
                    onValueChange={(value) =>
                      update({
                        expand_prefetch_scroll_pause: parseNumOrVar(value, 0.7)
                      })
                    }
                  />
                </CompactField>
                <CompactField
                  label={t('completionRetriesLabel')}
                  hint={t('completionRetriesHint')}
                >
                  <VariableValueInput
                    availableVariables={availableVariables}
                    value={String(step.expand_completion_retries ?? 1)}
                    onValueChange={(value) =>
                      update({
                        expand_completion_retries: parseNumOrVar(value, 1)
                      })
                    }
                  />
                </CompactField>
              </div>
            </CollapsibleBlock>
          ) : null}

          {step.stop_if_no_new && entity !== 'groups' ? (
            <StepPanelField label={t('noNewThresholdLabel')}>
              <div className='flex items-center gap-2'>
                <VariableValueInput
                  availableVariables={availableVariables}
                  value={String(step.no_new_threshold ?? 30)}
                  onValueChange={(value) =>
                    update({
                      no_new_threshold: parseNumOrVar(value, 30)
                    })
                  }
                />
                <span className='text-[11px] text-muted-foreground'>
                  {t('noNewThresholdUnit')}
                </span>
              </div>
              <p className='mt-1 text-[10px] text-muted-foreground'>
                {t('noNewThresholdHint')}
              </p>
            </StepPanelField>
          ) : null}
        </div>
      ) : null}

      {showDataSave ? (
        <div className='space-y-3'>
          <StepPanelSection
            title={t('resultSectionTitle')}
            badge={
              <Badge variant='outline' className='text-[10px] font-normal'>
                {t('resultSectionBadge')}
              </Badge>
            }
          >
            <StepPanelField label={t('resultVarLabel')}>
              <Input
                className='h-9 font-mono text-xs'
                placeholder={t('resultVarPlaceholder')}
                value={step.result_var ?? ''}
                onChange={(e) =>
                  update({ result_var: e.target.value || undefined })
                }
              />
              <p className='mt-1 text-[10px] text-muted-foreground'>
                {t('resultVarHint')}
              </p>
            </StepPanelField>
          </StepPanelSection>

          <StepPanelSection title={t('saveTitle')}>
            <StepPanelToggle
              label={t('saveEnableLabel')}
              description={saveEnabled ? undefined : t('saveEnableDescription')}
              checked={saveEnabled}
              onCheckedChange={(checked) => {
                if (checked) {
                  update({
                    collection: '${SAVE_COLLECTION}',
                    platform: entity === 'text_nodes' ? 'ui' : 'auto',
                    ...saveDefaultsForEntity(entity)
                  });
                } else {
                  const {
                    collection: _c,
                    platform: _p,
                    content_type: _ct,
                    dedupe_field: _d,
                    tags: _t,
                    save_parent_id_var: _sp,
                    item_level: _il,
                    ...rest
                  } = step;
                  onChange(rest as FlowStep);
                }
              }}
            />

            {saveEnabled ? (
              <div className='space-y-3'>
                <SaveSummaryCard
                  title={t('saveSummaryTitle')}
                  rows={saveSummaryRows}
                />

                <F label={t('saveCollectionLabel')}>
                  <VariableValueInput
                    availableVariables={availableVariables}
                    value={step.collection ?? ''}
                    placeholder={t('saveCollectionPlaceholder', {
                      varToken: SCENARIO_VAR_TOKENS.SAVE_COLLECTION
                    })}
                    onValueChange={(value) => update({ collection: value })}
                    insertMode='append'
                  />
                  <p className='mt-1 text-[10px] text-muted-foreground'>
                    {t('saveCollectionHint', {
                      varToken: SCENARIO_VAR_TOKENS.SAVE_COLLECTION
                    })}
                  </p>
                </F>

                <F label={t('saveDedupeLabel')}>
                  <select
                    className='h-9 w-full rounded-md border border-input bg-background px-2 text-xs'
                    value={
                      step.dedupe_field ??
                      saveDefaultsForEntity(entity).dedupe_field
                    }
                    onChange={(e) => update({ dedupe_field: e.target.value })}
                  >
                    {dedupeOptions.map((opt) => (
                      <option key={opt} value={opt}>
                        {labelDedupe(opt, entity, t)}
                      </option>
                    ))}
                  </select>
                  <p className='mt-1 text-[10px] text-muted-foreground'>
                    {t('saveDedupeHint')}
                  </p>
                </F>

                <CollapsibleBlock
                  title={t('saveAdvancedTitle')}
                  badge={
                    <Badge variant='outline' className='text-[9px] font-normal'>
                      {t('saveAdvancedBadge')}
                    </Badge>
                  }
                >
                  <StepPanelHint>{t('saveAdvancedHint')}</StepPanelHint>
                  <div className='grid grid-cols-2 gap-3'>
                    <F label={t('saveSummaryPlatform')}>
                      <Input
                        className='h-9 text-xs'
                        placeholder='auto'
                        value={step.platform ?? 'auto'}
                        onChange={(e) =>
                          update({ platform: e.target.value || undefined })
                        }
                      />
                    </F>
                    <F label={t('saveSummaryContentType')}>
                      <select
                        className='h-9 w-full rounded-md border border-input bg-background px-2 text-xs'
                        value={
                          step.content_type ??
                          saveDefaultsForEntity(entity).content_type
                        }
                        onChange={(e) =>
                          update({ content_type: e.target.value || undefined })
                        }
                      >
                        <option value='post'>
                          {t('saveContentTypeGenericPost')}
                        </option>
                        <option value='comment'>
                          {t('saveContentTypeGenericComment')}
                        </option>
                        <option value='text'>{t('saveContentTypeText')}</option>
                      </select>
                    </F>
                  </div>
                  <F label={t('saveTagsLabel')}>
                    <VariableValueInput
                      availableVariables={availableVariables}
                      placeholder={t('saveTagsPlaceholder')}
                      value={step.tags ?? ''}
                      onValueChange={(value) =>
                        update({ tags: value || undefined })
                      }
                      insertMode='append'
                    />
                    <p className='mt-1 text-[10px] text-muted-foreground'>
                      {t('saveTagsHint', {
                        varToken: SCENARIO_VAR_TOKENS.GROUP_NAME
                      })}
                    </p>
                  </F>
                  {entity === 'comments' ? (
                    <F label={t('saveParentLinkLabel')}>
                      <select
                        className='h-9 w-full rounded-md border border-input bg-background px-2 text-xs'
                        value={saveParentMode}
                        onChange={(e) => {
                          if (e.target.value === 'auto') {
                            update({ save_parent_id_var: undefined });
                          } else {
                            update({
                              save_parent_id_var:
                                step.save_parent_id_var &&
                                step.save_parent_id_var !==
                                  ACTIVE_SAVE_PARENT_VAR
                                  ? step.save_parent_id_var
                                  : ''
                            });
                          }
                        }}
                      >
                        <option value='auto'>{t('saveParentLinkAuto')}</option>
                        <option value='custom'>
                          {t('saveParentLinkCustom')}
                        </option>
                      </select>
                      {saveParentMode === 'custom' ? (
                        <Input
                          className='mt-1.5 h-9 font-mono text-xs'
                          placeholder={ACTIVE_SAVE_PARENT_VAR}
                          value={step.save_parent_id_var ?? ''}
                          onChange={(e) =>
                            update({
                              save_parent_id_var: e.target.value || undefined
                            })
                          }
                        />
                      ) : null}
                      <p className='mt-1 text-[10px] text-muted-foreground'>
                        {t('saveParentLinkHint')}
                      </p>
                    </F>
                  ) : null}
                  <F label={t('saveItemLevelLabel')}>
                    <select
                      className='h-9 w-full rounded-md border border-input bg-background px-2 text-xs'
                      value={String(step.item_level ?? 0)}
                      onChange={(e) =>
                        update({ item_level: Number(e.target.value) || 0 })
                      }
                    >
                      <option value='0'>{t('saveItemLevelPost')}</option>
                      <option value='1'>{t('saveItemLevelComment')}</option>
                      <option value='2'>{t('saveItemLevelReply')}</option>
                    </select>
                  </F>
                </CollapsibleBlock>
              </div>
            ) : null}
          </StepPanelSection>
        </div>
      ) : null}
    </div>
  );
}
