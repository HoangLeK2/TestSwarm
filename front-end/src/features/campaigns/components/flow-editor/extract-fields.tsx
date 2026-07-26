'use client';

import { useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { useTranslations } from 'next-intl';
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

type ExtractStep = FlowStep & {
  strategy?: string;
  edge_extra_data?: boolean;
  strategy_version?: string;
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
  max_items?: number | string;
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
  no_new_threshold?: number;
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
    value: 'fb_posts',
    titleKey: 'strategyPostsTitle',
    descKey: 'strategyPostsDesc'
  },
  {
    value: 'fb_comments',
    titleKey: 'strategyCommentsTitle',
    descKey: 'strategyCommentsDesc'
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

function saveDefaultsForStrategy(strategy: string): {
  content_type: string;
  dedupe_field: string;
} {
  if (strategy === 'fb_comments') {
    return { content_type: 'fb_comment', dedupe_field: 'comment_key' };
  }
  if (strategy === 'fb_posts') {
    return { content_type: 'fb_post', dedupe_field: 'post_key' };
  }
  return { content_type: 'text', dedupe_field: 'text' };
}

/** Switch extract strategy and drop fields that do not apply (update() cannot delete keys). */
function applyExtractStrategySwitch(
  step: ExtractStep,
  strategy: string,
  saveEnabled: boolean
): ExtractStep {
  const next: ExtractStep = { ...step, strategy };

  if (strategy === 'fb_posts') {
    next.edge_extra_data = step.edge_extra_data ?? true;
    next.strategy_version = 'fb_posts:v1';
    next.open_post_before_extract = true;
    next.open_post_press_back_after_extract = false;
    next.extract_profile = step.extract_profile ?? 'balanced';
  } else if (strategy === 'fb_comments') {
    next.edge_extra_data = step.edge_extra_data ?? true;
    next.strategy_version = 'fb_comments:v1';
    next.extract_profile = step.extract_profile ?? 'balanced';
    next.open_post_press_back_after_extract =
      step.open_post_press_back_after_extract ?? true;
    delete next.open_post_before_extract;
  } else if (strategy === 'text_nodes') {
    next.edge_extra_data = step.edge_extra_data ?? true;
    next.strategy_version = 'text_nodes:v1';
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
    Object.assign(next, saveDefaultsForStrategy(strategy));
    if (strategy !== 'fb_comments') {
      delete next.save_parent_id_var;
    }
    next.platform = strategy === 'text_nodes' ? 'ui' : 'facebook';
  }

  return next;
}

function labelPlatform(platform: string | undefined, t: (k: string) => string) {
  if (!platform || platform === 'facebook') return t('savePlatformFacebook');
  return platform;
}

function labelContentType(
  contentType: string | undefined,
  strategy: string,
  t: (k: string) => string
) {
  const ct = contentType ?? saveDefaultsForStrategy(strategy).content_type;
  if (ct === 'fb_comment') return t('saveContentTypeComment');
  if (ct === 'fb_post') return t('saveContentTypeGroupPost');
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
  strategy: string,
  t: (k: string) => string
) {
  const d = field ?? saveDefaultsForStrategy(strategy).dedupe_field;
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

function CollapsibleBlock({
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
  view = 'all'
}: {
  step: ExtractStep;
  update: (fields: Partial<FlowStep>) => void;
  onChange: (step: FlowStep) => void;
  view?: 'all' | 'screen' | 'data-save';
}) {
  const t = useTranslations('campaignsFeature.stepEditor.extract');
  const strategy = step.strategy ?? 'fb_posts';
  const expand = step.expand_see_more ?? true;
  const openPost =
    step.open_post_before_extract ?? (strategy === 'fb_posts' ? true : false);
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
      value: labelContentType(step.content_type, strategy, t)
    },
    {
      label: t('saveSummaryStorage'),
      value: labelCollection(step.collection, t)
    },
    {
      label: t('saveSummaryDedupe'),
      value: labelDedupe(step.dedupe_field, strategy, t)
    }
  ];

  const dedupeOptions =
    strategy === 'fb_comments'
      ? (['comment_key', 'text'] as const)
      : strategy === 'fb_posts'
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
                  selected={strategy === s.value}
                  selectedLabel={t('strategySelected')}
                  onSelect={() =>
                    onChange(
                      applyExtractStrategySwitch(step, s.value, saveEnabled)
                    )
                  }
                />
              ))}
            </div>
            <FlowStrip labels={flowLabels} />
          </StepPanelSection>

          <StepPanelSection title={t('behaviorSectionTitle')}>
            {strategy === 'fb_posts' || strategy === 'fb_comments' ? (
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
            {strategy === 'fb_posts' ? (
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
            {strategy === 'fb_comments' ? (
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
            {strategy !== 'fb_comments' ? (
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

          {strategy === 'fb_posts' ||
          strategy === 'fb_comments' ||
          strategy === 'text_nodes' ? (
            <StepPanelSection
              title={t('facebookExtraTitle')}
              badge={
                <Badge variant='outline' className='text-[10px] font-normal'>
                  {t('facebookExtraBadge')}
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
                    step.strategy_version ??
                    (strategy === 'fb_comments'
                      ? 'fb_comments:v1'
                      : strategy === 'text_nodes'
                        ? 'text_nodes:v1'
                        : 'fb_posts:v1')
                  }
                />
              </CompactField>

              {strategy === 'fb_comments' ? (
                <div className='space-y-3 rounded-lg border border-border/60 bg-muted/20 p-3'>
                  <div className='grid grid-cols-2 gap-3'>
                    <CompactField
                      label={t('maxItemsLabel')}
                      hint={t('maxItemsHint')}
                    >
                      <Input
                        className='h-8 w-full font-mono text-xs'
                        value={String(step.max_items ?? 220)}
                        onChange={(e) =>
                          update({
                            max_items: parseNumOrVar(e.target.value, 220)
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
                          placeholder='_fb_comment_parent_pid'
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
                      <Input
                        className='h-8 font-mono text-xs'
                        value={String(step.comment_scroll_passes ?? 16)}
                        onChange={(e) =>
                          update({
                            comment_scroll_passes: parseNumOrVar(
                              e.target.value,
                              16
                            )
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('commentSwipesPerDumpLabel')}
                      hint={t('commentSwipesPerDumpHint')}
                    >
                      <Input
                        className='h-8 font-mono text-xs'
                        value={String(step.comment_swipes_per_dump ?? 4)}
                        onChange={(e) =>
                          update({
                            comment_swipes_per_dump: parseNumOrVar(
                              e.target.value,
                              4
                            )
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('commentScrollDistanceLabel')}
                      hint={t('commentScrollDistanceHint')}
                    >
                      <Input
                        className='h-8 font-mono text-xs'
                        value={String(step.comment_scroll_distance ?? 0.52)}
                        onChange={(e) =>
                          update({
                            comment_scroll_distance: parseNumOrVar(
                              e.target.value,
                              0.52
                            )
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('commentScrollDurationLabel')}
                      hint={t('commentScrollDurationHint')}
                    >
                      <Input
                        className='h-8 font-mono text-xs'
                        value={String(step.comment_scroll_duration_ms ?? 120)}
                        onChange={(e) =>
                          update({
                            comment_scroll_duration_ms: parseNumOrVar(
                              e.target.value,
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
                      <Input
                        className='h-8 font-mono text-xs'
                        value={String(step.comment_scroll_pause_s ?? 0.03)}
                        onChange={(e) =>
                          update({
                            comment_scroll_pause_s: parseNumOrVar(
                              e.target.value,
                              0.03
                            )
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
                      <Input
                        className='h-8 font-mono text-xs'
                        value={String(step.comment_no_growth_break ?? 0)}
                        onChange={(e) =>
                          update({
                            comment_no_growth_break: parseNumOrVar(
                              e.target.value,
                              0
                            )
                          })
                        }
                      />
                    </CompactField>
                    <CompactField
                      label={t('minCommentScanPassesLabel')}
                      hint={t('minCommentScanPassesHint')}
                    >
                      <Input
                        className='h-8 font-mono text-xs'
                        value={String(step.min_comment_scan_passes ?? 2)}
                        onChange={(e) =>
                          update({
                            min_comment_scan_passes: parseNumOrVar(
                              e.target.value,
                              2
                            )
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
                  <Input
                    className='h-8 font-mono text-xs'
                    value={String(step.expand_see_more_max_passes ?? 2)}
                    onChange={(e) =>
                      update({
                        expand_see_more_max_passes: parseNumOrVar(
                          e.target.value,
                          2
                        )
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
                  <Input
                    className='h-8 font-mono text-xs'
                    value={String(step.expand_see_more_scroll_distance ?? 0.3)}
                    onChange={(e) =>
                      update({
                        expand_see_more_scroll_distance: parseNumOrVar(
                          e.target.value,
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
                  <Input
                    className='h-8 font-mono text-xs'
                    value={String(step.expand_lazy_hydration_rounds ?? 6)}
                    onChange={(e) =>
                      update({
                        expand_lazy_hydration_rounds: parseNumOrVar(
                          e.target.value,
                          6
                        )
                      })
                    }
                  />
                </CompactField>
                <CompactField
                  label={t('lazyHydrationScrollDistanceLabel')}
                  hint={t('lazyHydrationScrollDistanceHint')}
                >
                  <Input
                    className='h-8 font-mono text-xs'
                    value={String(step.expand_lazy_scroll_distance ?? 0.3)}
                    onChange={(e) =>
                      update({
                        expand_lazy_scroll_distance: parseNumOrVar(
                          e.target.value,
                          0.3
                        )
                      })
                    }
                  />
                </CompactField>
                <CompactField
                  label={t('prefetchScrollPassesLabel')}
                  hint={t('prefetchScrollPassesHint')}
                >
                  <Input
                    className='h-8 font-mono text-xs'
                    value={String(step.expand_prefetch_scroll_passes ?? 0)}
                    onChange={(e) =>
                      update({
                        expand_prefetch_scroll_passes: parseNumOrVar(
                          e.target.value,
                          0
                        )
                      })
                    }
                  />
                </CompactField>
                <CompactField
                  label={t('prefetchScrollPauseLabel')}
                  hint={t('prefetchScrollPauseHint')}
                >
                  <Input
                    className='h-8 font-mono text-xs'
                    value={String(step.expand_prefetch_scroll_pause ?? 0.7)}
                    onChange={(e) =>
                      update({
                        expand_prefetch_scroll_pause: parseNumOrVar(
                          e.target.value,
                          0.7
                        )
                      })
                    }
                  />
                </CompactField>
                <CompactField
                  label={t('completionRetriesLabel')}
                  hint={t('completionRetriesHint')}
                >
                  <Input
                    className='h-8 font-mono text-xs'
                    value={String(step.expand_completion_retries ?? 1)}
                    onChange={(e) =>
                      update({
                        expand_completion_retries: parseNumOrVar(
                          e.target.value,
                          1
                        )
                      })
                    }
                  />
                </CompactField>
              </div>
            </CollapsibleBlock>
          ) : null}

          {step.stop_if_no_new ? (
            <StepPanelField label={t('noNewThresholdLabel')}>
              <div className='flex items-center gap-2'>
                <Input
                  type='number'
                  min={1}
                  className='h-9 w-24 text-xs'
                  value={step.no_new_threshold ?? 30}
                  onChange={(e) =>
                    update({ no_new_threshold: Number(e.target.value) || 30 })
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
                    platform: strategy === 'text_nodes' ? 'ui' : 'facebook',
                    ...saveDefaultsForStrategy(strategy)
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
                  <Input
                    className='h-9 text-xs'
                    placeholder={t('saveCollectionPlaceholder', {
                      varToken: SCENARIO_VAR_TOKENS.SAVE_COLLECTION
                    })}
                    value={step.collection ?? ''}
                    onChange={(e) => update({ collection: e.target.value })}
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
                      saveDefaultsForStrategy(strategy).dedupe_field
                    }
                    onChange={(e) => update({ dedupe_field: e.target.value })}
                  >
                    {dedupeOptions.map((opt) => (
                      <option key={opt} value={opt}>
                        {labelDedupe(opt, strategy, t)}
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
                        placeholder='facebook'
                        value={step.platform ?? 'facebook'}
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
                          saveDefaultsForStrategy(strategy).content_type
                        }
                        onChange={(e) =>
                          update({ content_type: e.target.value || undefined })
                        }
                      >
                        <option value='fb_post'>
                          {t('saveContentTypeGroupPost')}
                        </option>
                        <option value='fb_comment'>
                          {t('saveContentTypeComment')}
                        </option>
                        <option value='text'>{t('saveContentTypeText')}</option>
                      </select>
                    </F>
                  </div>
                  <F label={t('saveTagsLabel')}>
                    <Input
                      className='h-9 text-xs'
                      placeholder={t('saveTagsPlaceholder')}
                      value={step.tags ?? ''}
                      onChange={(e) =>
                        update({ tags: e.target.value || undefined })
                      }
                    />
                    <p className='mt-1 text-[10px] text-muted-foreground'>
                      {t('saveTagsHint', {
                        varToken: SCENARIO_VAR_TOKENS.GROUP_NAME
                      })}
                    </p>
                  </F>
                  {strategy === 'fb_comments' ? (
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
