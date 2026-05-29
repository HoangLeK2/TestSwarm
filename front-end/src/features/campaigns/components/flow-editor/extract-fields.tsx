'use client';

import { useState, type ReactNode } from 'react';
import { ChevronDown } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { FlowStep } from '../scenario-steps/types';
import {
  F,
  StepPanelField,
  StepPanelHint,
  StepPanelSection,
  StepPanelToggle
} from './step-panel-primitives';

type ExtractStep = FlowStep & {
  strategy?: string;
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

const STRATEGIES = [
  { value: 'fb_posts', titleKey: 'strategyPostsTitle', descKey: 'strategyPostsDesc' },
  {
    value: 'fb_comments',
    titleKey: 'strategyCommentsTitle',
    descKey: 'strategyCommentsDesc'
  },
  { value: 'text_nodes', titleKey: 'strategyTextTitle', descKey: 'strategyTextDesc' }
] as const;

const FLOW_STEPS = ['flowRead', 'flowExpand', 'flowScroll', 'flowSave'] as const;

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
        <Badge variant='secondary' className='mt-0.5 w-fit px-1.5 py-0 text-[9px]'>
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
      <span className='text-[10px] font-medium text-muted-foreground'>{label}</span>
      {children}
      {hint ? (
        <p className='text-[9px] leading-relaxed text-muted-foreground/90'>{hint}</p>
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
    return { content_type: 'comment', dedupe_field: 'comment_key' };
  }
  if (strategy === 'fb_posts') {
    return { content_type: 'group_post', dedupe_field: 'post_key' };
  }
  return { content_type: 'text', dedupe_field: 'text' };
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
  const ct =
    contentType ?? saveDefaultsForStrategy(strategy).content_type;
  if (ct === 'comment') return t('saveContentTypeComment');
  if (ct === 'group_post') return t('saveContentTypeGroupPost');
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
  onChange
}: {
  step: ExtractStep;
  update: (fields: Partial<FlowStep>) => void;
  onChange: (step: FlowStep) => void;
}) {
  const t = useTranslations('campaignsFeature.stepEditor.extract');
  const strategy = step.strategy ?? 'fb_posts';
  const expand = step.expand_see_more ?? true;
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

  return (
    <div className='space-y-3'>
      <StepPanelHint>{t('intro')}</StepPanelHint>

      <StepPanelSection title={t('sourceSectionTitle')}>
        <div className='flex gap-2'>
          {STRATEGIES.map((s) => (
            <StrategyCard
              key={s.value}
              title={t(s.titleKey)}
              description={t(s.descKey)}
              selected={strategy === s.value}
              selectedLabel={t('strategySelected')}
              onSelect={() => {
                const patch: Partial<FlowStep> = { strategy: s.value };
                if (saveEnabled) {
                  Object.assign(patch, saveDefaultsForStrategy(s.value));
                  if (s.value !== 'fb_comments') {
                    patch.save_parent_id_var = undefined;
                  }
                }
                update(patch);
              }}
            />
          ))}
        </div>
        <FlowStrip labels={flowLabels} />
      </StepPanelSection>

      <StepPanelSection title={t('behaviorSectionTitle')}>
        <StepPanelToggle
          label={t('expandSeeMoreLabel')}
          description={t('expandSeeMoreDescription')}
          checked={expand}
          onCheckedChange={(checked) => update({ expand_see_more: checked })}
        />
        <StepPanelToggle
          label={t('stopIfNoNewLabel')}
          description={t('stopIfNoNewDescription')}
          checked={step.stop_if_no_new ?? true}
          onCheckedChange={(checked) => update({ stop_if_no_new: checked })}
        />
      </StepPanelSection>

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
            <CompactField label={t('maxPassesLabel')} hint={t('maxPassesHint')}>
              <Input
                className='h-8 font-mono text-xs'
                value={String(step.expand_see_more_max_passes ?? 2)}
                onChange={(e) =>
                  update({
                    expand_see_more_max_passes: parseNumOrVar(e.target.value, 2)
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
                    expand_lazy_hydration_rounds: parseNumOrVar(e.target.value, 6)
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
                    expand_lazy_scroll_distance: parseNumOrVar(e.target.value, 0.3)
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
                    expand_prefetch_scroll_passes: parseNumOrVar(e.target.value, 0)
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
                    expand_prefetch_scroll_pause: parseNumOrVar(e.target.value, 0.7)
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
                    expand_completion_retries: parseNumOrVar(e.target.value, 1)
                  })
                }
              />
            </CompactField>
          </div>
        </CollapsibleBlock>
      ) : null}

      {strategy === 'fb_comments' ? (
        <StepPanelSection title={t('commentsSectionTitle')}>
          <div className='grid grid-cols-2 gap-3'>
            <StepPanelField label={t('maxItemsLabel')}>
              <Input
                className='h-9 w-full font-mono text-xs'
                value={String(step.max_items ?? 50)}
                onChange={(e) =>
                  update({ max_items: parseNumOrVar(e.target.value, 50) })
                }
              />
              <p className='mt-1 text-[10px] text-muted-foreground'>
                {t('maxItemsHint')}
              </p>
            </StepPanelField>
            <StepPanelField label={t('parentPostIdVarLabel')}>
              <select
                className='h-9 w-full rounded-md border border-input bg-background px-2 text-xs'
                value={extractParentMode}
                onChange={(e) => {
                  if (e.target.value === 'auto') {
                    update({ parent_post_id_var: undefined });
                  } else {
                    update({
                      parent_post_id_var: step.parent_post_id_var || ''
                    });
                  }
                }}
              >
                <option value='auto'>{t('parentPostModeAuto')}</option>
                <option value='custom'>{t('parentPostModeCustom')}</option>
              </select>
              {extractParentMode === 'custom' ? (
                <Input
                  className='mt-1.5 h-9 font-mono text-xs'
                  placeholder='_active_comment_parent_hash'
                  value={step.parent_post_id_var ?? ''}
                  onChange={(e) =>
                    update({
                      parent_post_id_var: e.target.value || undefined
                    })
                  }
                />
              ) : null}
              <p className='mt-1 text-[10px] text-muted-foreground'>
                {t('parentPostIdVarHint')}
              </p>
            </StepPanelField>
          </div>
        </StepPanelSection>
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
            onChange={(e) => update({ result_var: e.target.value || undefined })}
          />
          <p className='mt-1 text-[10px] text-muted-foreground'>
            {t('resultVarHint')}
          </p>
        </StepPanelField>
      </StepPanelSection>

      <StepPanelSection title={t('saveTitle')}>
        <StepPanelToggle
          label={t('saveEnableLabel')}
          description={
            saveEnabled ? undefined : t('saveEnableDescription')
          }
          checked={saveEnabled}
          onCheckedChange={(checked) => {
            if (checked) {
              update({
                collection: '${SAVE_COLLECTION}',
                platform: 'facebook',
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
            <SaveSummaryCard title={t('saveSummaryTitle')} rows={saveSummaryRows} />

            <F label={t('saveCollectionLabel')}>
              <Input
                className='h-9 text-xs'
                placeholder={t('saveCollectionPlaceholder')}
                value={step.collection ?? ''}
                onChange={(e) => update({ collection: e.target.value })}
              />
              <p className='mt-1 text-[10px] text-muted-foreground'>
                {t('saveCollectionHint')}
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
                    <option value='group_post'>
                      {t('saveContentTypeGroupPost')}
                    </option>
                    <option value='comment'>{t('saveContentTypeComment')}</option>
                    <option value='text'>{t('saveContentTypeText')}</option>
                  </select>
                </F>
              </div>
              <F label={t('saveTagsLabel')}>
                <Input
                  className='h-9 text-xs'
                  placeholder={t('saveTagsPlaceholder')}
                  value={step.tags ?? ''}
                  onChange={(e) => update({ tags: e.target.value || undefined })}
                />
                <p className='mt-1 text-[10px] text-muted-foreground'>
                  {t('saveTagsHint')}
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
                            step.save_parent_id_var !== ACTIVE_SAVE_PARENT_VAR
                              ? step.save_parent_id_var
                              : ''
                        });
                      }
                    }}
                  >
                    <option value='auto'>{t('saveParentLinkAuto')}</option>
                    <option value='custom'>{t('saveParentLinkCustom')}</option>
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
  );
}
