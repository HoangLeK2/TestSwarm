'use client';

import { useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { ChevronRight, List, Search, Workflow } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { StepIcon } from '@/features/campaigns/components/flow-editor/step-icon';
import type { ScenarioTemplateOut } from '@/features/scenario-templates/services/api';
import { cn } from '@/lib/utils';

type StepPickerItem = {
  type: string;
  label: string;
  onClick: () => void;
};

type SectionConfig = {
  key: string;
  title: string;
  items: StepPickerItem[];
  iconWrap: string;
  cardHover: string;
  bar: string;
};

function StepPickerTile({
  item,
  iconWrap,
  cardHover,
  dense
}: {
  item: StepPickerItem;
  iconWrap: string;
  cardHover: string;
  dense?: boolean;
}) {
  return (
    <button
      type='button'
      onClick={item.onClick}
      className={cn(
        'group flex items-center rounded-lg border border-border/60 bg-background text-left font-medium text-foreground/90 transition',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30',
        dense
          ? 'min-h-9 gap-1.5 px-2 py-1.5 text-[11px]'
          : 'min-h-[52px] gap-2.5 px-2.5 text-xs',
        cardHover
      )}
    >
      <span
        className={cn(
          'flex shrink-0 items-center justify-center rounded-md ring-1 ring-inset transition group-hover:scale-105',
          dense ? 'h-7 w-7' : 'h-8 w-8',
          iconWrap
        )}
      >
        <StepIcon type={item.type as any} size={dense ? 14 : 15} />
      </span>
      <span className='truncate leading-snug'>{item.label}</span>
    </button>
  );
}

function StepSection({
  section,
  dense
}: {
  section: SectionConfig;
  dense?: boolean;
}) {
  return (
    <section className='overflow-hidden rounded-lg border border-border/60 bg-card/80'>
      <header
        className={cn(
          'flex items-center gap-2 border-b border-border/40 bg-muted/20',
          dense ? 'px-2.5 py-1.5' : 'px-4 py-2.5'
        )}
      >
        <span className={cn('h-3 w-1 rounded-full', section.bar)} aria-hidden />
        <h4
          className={cn(
            'font-medium text-foreground',
            dense ? 'text-xs' : 'text-sm'
          )}
        >
          {section.title}
        </h4>
        <Badge
          variant='secondary'
          className='ml-auto h-5 px-1.5 text-[10px] font-semibold tabular-nums'
        >
          {section.items.length}
        </Badge>
      </header>
      <div
        className={cn(
          'grid gap-1.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,150px),1fr))]',
          dense
            ? 'p-2 xl:[grid-template-columns:repeat(auto-fit,minmax(min(100%,136px),1fr))]'
            : 'gap-2 p-3 sm:[grid-template-columns:repeat(auto-fit,minmax(min(100%,170px),1fr))]'
        )}
      >
        {section.items.map((item) => (
          <StepPickerTile
            key={item.type}
            item={item}
            dense={dense}
            iconWrap={section.iconWrap}
            cardHover={section.cardHover}
          />
        ))}
      </div>
    </section>
  );
}

export type EmptyNodePickerProps = {
  templates: ScenarioTemplateOut[] | undefined;
  templatesLoading: boolean;
  onPreviewTemplate: (template: ScenarioTemplateOut) => void;
  onAddFlow: (type: string) => void;
  onAddWait: () => void;
  /** Control-record studio layout — dense tiles, fills column scroll area. */
  dense?: boolean;
};

export function EmptyNodePicker({
  templates,
  templatesLoading,
  onPreviewTemplate,
  onAddFlow,
  onAddWait,
  dense = false
}: EmptyNodePickerProps) {
  const t = useTranslations('devicesControlRecord.view.emptyNodePicker');
  const [templateQuery, setTemplateQuery] = useState('');

  const interactions: StepPickerItem[] = useMemo(
    () => [
      {
        type: 'tap_selector',
        label: t('tapSelector'),
        onClick: () => onAddFlow('tap_selector')
      },
      {
        type: 'long_tap_selector',
        label: t('longTap'),
        onClick: () => onAddFlow('long_tap_selector')
      },
      {
        type: 'input_selector',
        label: t('inputText'),
        onClick: () => onAddFlow('input_selector')
      },
      {
        type: 'assert_element',
        label: t('assertElement'),
        onClick: () => onAddFlow('assert_element')
      },
      {
        type: 'tap_ratio',
        label: t('tapRatio'),
        onClick: () => onAddFlow('tap_ratio')
      },
      {
        type: 'swipe_ratio',
        label: t('swipe'),
        onClick: () => onAddFlow('swipe_ratio')
      },
      {
        type: 'key',
        label: t('keyPress'),
        onClick: () => onAddFlow('key')
      },
      {
        type: 'set_variable',
        label: t('setVariable'),
        onClick: () => onAddFlow('set_variable')
      }
    ],
    [onAddFlow, t]
  );

  const flow: StepPickerItem[] = useMemo(
    () => [
      {
        type: 'wait',
        label: t('waitSeconds'),
        onClick: onAddWait
      },
      {
        type: 'wait_element',
        label: t('waitElement'),
        onClick: () => onAddFlow('wait_element')
      },
      {
        type: 'if_element',
        label: t('ifElement'),
        onClick: () => onAddFlow('if_element')
      },
      {
        type: 'if_variable',
        label: t('ifVariable'),
        onClick: () => onAddFlow('if_variable')
      },
      {
        type: 'repeat',
        label: t('repeatN'),
        onClick: () => onAddFlow('repeat')
      },
      {
        type: 'repeat_until',
        label: t('repeatUntil'),
        onClick: () => onAddFlow('repeat_until')
      }
    ],
    [onAddFlow, onAddWait, t]
  );

  const sections: SectionConfig[] = useMemo(
    () => [
      {
        key: 'interaction',
        title: t('sectionInteraction'),
        items: interactions,
        bar: 'bg-indigo-500',
        iconWrap: 'bg-indigo-50 text-indigo-600 ring-indigo-100',
        cardHover:
          'hover:border-indigo-300/80 hover:bg-indigo-50/50 hover:shadow-sm'
      },
      {
        key: 'flow',
        title: t('sectionFlow'),
        items: flow,
        bar: 'bg-amber-500',
        iconWrap: 'bg-amber-50 text-amber-600 ring-amber-100',
        cardHover:
          'hover:border-amber-300/80 hover:bg-amber-50/50 hover:shadow-sm'
      }
    ],
    [flow, interactions, t]
  );

  const filteredTemplates = useMemo(() => {
    const list = templates ?? [];
    const q = templateQuery.trim().toLowerCase();
    if (!q) return list;
    return list.filter((tpl) => {
      const name = (tpl.name ?? '').toLowerCase();
      const desc = (tpl.description ?? '').toLowerCase();
      const category = (tpl.category ?? '').toLowerCase();
      return name.includes(q) || desc.includes(q) || category.includes(q);
    });
  }, [templateQuery, templates]);

  const templateCount = templates?.length ?? 0;

  return (
    <div
      className={cn(
        'flex h-full min-h-0 flex-col',
        dense ? 'overflow-hidden' : 'w-full px-4 py-4 sm:px-6 sm:py-6'
      )}
    >
      <div
        className={cn(
          'w-full space-y-3',
          dense
            ? 'flex min-h-0 flex-1 flex-col overflow-hidden'
            : 'max-w-[min(100%,980px)] space-y-5'
        )}
      >
        <div
          className={cn(
            dense
              ? 'shrink-0 border-b border-border/50 px-3 py-2.5'
              : 'flex flex-col items-center text-center'
          )}
        >
          {dense ? (
            <div className='flex items-start gap-2.5'>
              <div className='flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted/70 ring-1 ring-border/50'>
                <Workflow
                  className='size-4 text-muted-foreground/80'
                  strokeWidth={1.5}
                />
              </div>
              <div className='min-w-0 flex-1'>
                <h3 className='text-sm font-semibold leading-tight text-foreground'>
                  {t('title')}
                </h3>
                <p className='mt-0.5 text-[11px] leading-snug text-muted-foreground'>
                  {t('subtitle')}
                </p>
              </div>
            </div>
          ) : (
            <>
              <div className='mb-3 flex size-14 items-center justify-center rounded-full bg-muted/70 ring-1 ring-border/50'>
                <Workflow
                  className='size-7 text-muted-foreground/80'
                  strokeWidth={1.5}
                />
              </div>
              <h3 className='text-lg font-semibold tracking-tight text-foreground'>
                {t('title')}
              </h3>
              <p className='mt-1.5 max-w-md text-sm leading-relaxed text-muted-foreground'>
                {t('subtitle')}
              </p>
            </>
          )}
        </div>

        <Tabs
          defaultValue='steps'
          className={cn(
            'w-full',
            dense && 'flex min-h-0 flex-1 flex-col overflow-hidden'
          )}
        >
          <TabsList
            className={cn(
              'grid h-8 w-full grid-cols-2',
              dense ? 'mx-3 shrink-0' : 'mx-auto h-9 max-w-sm'
            )}
          >
            <TabsTrigger value='steps' className='text-xs'>
              {t('tabSteps')}
            </TabsTrigger>
            <TabsTrigger value='templates' className='text-xs'>
              {t('tabTemplates')}
              {templateCount > 0 && (
                <span className='ml-1 rounded-full bg-muted px-1.5 py-0 text-[10px] font-semibold tabular-nums text-muted-foreground'>
                  {templateCount}
                </span>
              )}
            </TabsTrigger>
          </TabsList>

          <TabsContent
            value='steps'
            className={cn(
              dense
                ? 'mt-2 min-h-0 flex-1 overflow-y-auto px-3 pb-3'
                : 'mt-4 space-y-4'
            )}
          >
            <div className={cn(dense && 'space-y-2')}>
              {sections.map((section) => (
                <StepSection
                  key={section.key}
                  section={section}
                  dense={dense}
                />
              ))}
            </div>
            <p
              className={cn(
                'border border-dashed border-border/70 bg-muted/25 text-muted-foreground',
                dense
                  ? 'mt-2 rounded-md px-2.5 py-2 text-[10px] leading-snug'
                  : 'rounded-lg px-3.5 py-3 text-xs leading-relaxed'
              )}
            >
              {t('recordingTip')}
            </p>
          </TabsContent>

          <TabsContent
            value='templates'
            className={cn(
              dense
                ? 'mt-2 min-h-0 flex-1 overflow-y-auto px-3 pb-3'
                : 'mt-4 space-y-3'
            )}
          >
            <div className='relative'>
              <Search className='pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground' />
              <Input
                value={templateQuery}
                onChange={(e) => setTemplateQuery(e.target.value)}
                placeholder={t('templateSearchPlaceholder')}
                className={cn(
                  'bg-background pl-8 text-xs',
                  dense ? 'h-8' : 'h-9'
                )}
                disabled={templatesLoading || templateCount === 0}
              />
            </div>

            {templatesLoading ? (
              <div className='rounded-xl border border-dashed border-border/60 bg-card/50 px-4 py-8 text-center text-xs text-muted-foreground'>
                {t('templateLoading')}
              </div>
            ) : templateCount === 0 ? (
              <div className='rounded-xl border border-dashed border-border/60 bg-card/50 px-4 py-8 text-center text-xs leading-relaxed text-muted-foreground'>
                {t('templateEmpty')}
              </div>
            ) : filteredTemplates.length === 0 ? (
              <div className='rounded-xl border border-dashed border-border/60 bg-card/50 px-4 py-8 text-center text-xs text-muted-foreground'>
                {t('templateNoResults')}
              </div>
            ) : (
              <ul className={cn(dense ? 'space-y-1.5' : 'space-y-2')}>
                {filteredTemplates.map((tpl) => {
                  const stepCount = Array.isArray(tpl.steps)
                    ? tpl.steps.length
                    : 0;
                  return (
                    <li key={tpl.id}>
                      <button
                        type='button'
                        onClick={() => onPreviewTemplate(tpl)}
                        className={cn(
                          'group flex w-full items-start text-left transition',
                          dense
                            ? 'gap-2 rounded-lg border border-border/60 bg-card/80 px-2.5 py-2'
                            : 'gap-3 rounded-xl border border-border/60 bg-card/80 px-3 py-2.5 shadow-sm',
                          'hover:border-emerald-300/80 hover:bg-emerald-50/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500/25'
                        )}
                      >
                        <span
                          className={cn(
                            'flex shrink-0 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600 ring-1 ring-inset ring-emerald-100 transition group-hover:scale-105',
                            dense ? 'mt-0 h-8 w-8' : 'mt-0.5 h-9 w-9'
                          )}
                        >
                          <List size={dense ? 14 : 16} />
                        </span>
                        <span className='min-w-0 flex-1 space-y-1'>
                          <span className='flex flex-wrap items-center gap-1.5'>
                            <span className='text-sm font-medium text-foreground'>
                              {tpl.name}
                            </span>
                            {tpl.is_builtin && (
                              <Badge
                                variant='secondary'
                                className='h-4 px-1 text-[9px] font-semibold uppercase tracking-wide'
                              >
                                {t('templateBuiltinBadge')}
                              </Badge>
                            )}
                          </span>
                          <span className='block text-xs text-muted-foreground'>
                            {t('templateStepCount', { count: stepCount })}
                            {tpl.description ? ` · ${tpl.description}` : ''}
                          </span>
                          <span className='block text-[11px] text-muted-foreground/80'>
                            {t('templatePreviewHint')}
                          </span>
                        </span>
                        <ChevronRight className='mt-2 size-4 shrink-0 text-muted-foreground/50 transition group-hover:translate-x-0.5 group-hover:text-emerald-600' />
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
