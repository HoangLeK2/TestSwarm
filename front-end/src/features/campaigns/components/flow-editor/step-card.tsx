'use client';

import {
  Trash2,
  Play,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Crosshair,
  MousePointerClick,
  Move,
  Square,
  ChevronUp,
  ChevronDown
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { cn } from '@/lib/utils';
import { useOrgScenarios } from '@/features/org-scenarios/hooks/use-org-scenarios';
import type { FlowStep } from '../scenario-steps/types';
import {
  STEP_COLORS,
  formatStepLabelForCard,
  getStepCategory
} from './constants';
import { useCampaignFlowI18n } from './flow-i18n';
import { useImageTemplateUrl } from './image-template-scenario';
import { StepIcon } from './step-icon';
import {
  resolveVariablePreviewText,
  type VariablePreviewValues
} from './variable-preview';
import { analyzeStepConfiguration } from '../../lib/step-configuration-status';
import type { StepVariableLineage } from '../../lib/step-variable-lineage';
import { scenarioLintIssueSeverity } from '../../lib/scenario-lint-preflight';
import { resolveRunScenarioDisplayRef } from './run-scenario-card-label';
import { contentInteractionPresentation } from './content-interaction-presentation';
import type { RunScenarioCampaignOption } from '../scenario-steps/run-scenario-options';

/** Build an <img> src from a stored image value (base64, object-storage URL, or local /captures/ path). */
function stepImageSrc(val: string): string {
  if (!val) return '';
  if (val.startsWith('http') || val.startsWith('/')) return val;
  return `data:image/jpeg;base64,${val}`;
}

/** Get the full-screen image for a tap step (element crops are not persisted). */
function getTapStepImage(step: FlowStep): string {
  const screen = step.screen as
    | { element_image?: string; screenshot?: string }
    | undefined;
  const raw = screen?.screenshot || '';
  return raw ? stepImageSrc(raw) : '';
}

/**
 * Template thumbnail for a tap_image step.
 *
 * Unlike `tap`, whose screenshot rides along inside the step, the template is an
 * object-storage key — the point of the card image here is that "ảnh mẫu đã
 * gắn" tells you nothing about *which* button the step taps.
 */
function TapImageThumb({ step }: { step: FlowStep }) {
  const templateKey = step.template_key as string | undefined;
  const { url, forget } = useImageTemplateUrl(templateKey);
  if (!url) return null;
  return (
    // eslint-disable-next-line @next/next/no-img-element -- object-storage template thumbnails are already pre-sized.
    <img
      src={url}
      alt=''
      loading='lazy'
      decoding='async'
      onError={forget}
      className='h-12 w-12 shrink-0 rounded border border-border/40 bg-muted/40 object-contain'
    />
  );
}

interface Props {
  step: FlowStep;
  index: number;
  selected: boolean;
  compact?: boolean;
  onClick: () => void;
  onRemove: () => void;
  onRun?: () => void;
  runState?: 'idle' | 'running' | 'ok' | 'error';
  onStopInlineRun?: () => void;
  isPickTarget?: boolean;
  onTogglePickSelector?: () => void;
  coordPickActive?: 'tap_point' | 'swipe_segment' | null;
  onTogglePickTapCoords?: () => void;
  onTogglePickSwipeCoords?: () => void;
  reorderControls?: {
    canMoveUp: boolean;
    canMoveDown: boolean;
    onMoveUp: () => void;
    onMoveDown: () => void;
  };
  variablePreviewValues?: VariablePreviewValues;
  variableLineage?: StepVariableLineage;
  campaignScenarios?: RunScenarioCampaignOption[];
}

export function StepCard({
  step,
  selected,
  compact = false,
  onClick,
  onRemove,
  onRun,
  runState = 'idle',
  onStopInlineRun,
  isPickTarget,
  onTogglePickSelector,
  coordPickActive,
  onTogglePickTapCoords,
  onTogglePickSwipeCoords,
  reorderControls,
  variablePreviewValues,
  variableLineage,
  campaignScenarios = []
}: Props) {
  const tFlow = useTranslations('campaignsFeature.flowBracket');
  const tField = useTranslations('campaignsFeature.stepEditor.stepFields');
  const tConfig = useTranslations(
    'campaignsFeature.stepEditor.configurationStatus'
  );
  const tLineage = useTranslations(
    'campaignsFeature.stepEditor.variableLineage'
  );
  const { getStepTypeName, getStepDisplay } = useCampaignFlowI18n();
  const tPostFlow = useTranslations('campaignsFeature.stepEditor.postFlow');
  const postFlow = contentInteractionPresentation(step, variablePreviewValues);
  const colorCls = STEP_COLORS[step.type] ?? 'border-l-gray-400';
  const typeName = postFlow.isPost
    ? tPostFlow('findPost')
    : postFlow.isLike
      ? tPostFlow('likePost')
      : postFlow.isComment
        ? tPostFlow('commentPost')
        : formatStepLabelForCard(getStepTypeName(step.type));
  const { target: rawTarget, selectorBadge } = getStepDisplay(step);
  const target = resolveVariablePreviewText(rawTarget, variablePreviewValues);
  const category = getStepCategory(step.type);

  const title = (step.title as string | undefined)?.trim() || undefined;
  const description =
    (step.description as string | undefined)?.trim() || undefined;
  const runScenarioId =
    step.type === 'run_scenario'
      ? String((step as any).scenario_id || '').trim()
      : '';
  const { data: orgScenarios } = useOrgScenarios({
    enabled: step.type === 'run_scenario' && !!runScenarioId
  });
  const runScenarioRef =
    step.type === 'run_scenario'
      ? resolveRunScenarioDisplayRef(step, { campaignScenarios, orgScenarios })
      : '';
  const runScenarioEmptyHint =
    step.type === 'run_scenario' && !title && !runScenarioRef
      ? tFlow('runScenario.cardPickHint')
      : '';
  const postFlowSummary = postFlow.isPost
    ? postFlow.identity || tPostFlow('findPostMissing')
    : postFlow.isLike
      ? step.require_verified_target
        ? tPostFlow('afterVerifiedPost')
        : tPostFlow('noVerifiedPost')
      : postFlow.isComment
        ? postFlow.commentReady
          ? tPostFlow('commentPreview', { text: postFlow.commentPreview })
          : tPostFlow('commentMissing')
        : '';
  const secondRowMain =
    title ||
    postFlowSummary ||
    (step.type === 'run_scenario' ? runScenarioRef : target) ||
    runScenarioEmptyHint;
  const configurationStatus = analyzeStepConfiguration(step);
  const configurationIssueCount = configurationStatus.issues.length;
  const variableIssueCount = variableLineage?.issues.length ?? 0;
  const variableCriticalIssueCount =
    variableLineage?.issues.filter(
      (issue) => scenarioLintIssueSeverity(issue) === 'critical'
    ).length ?? 0;

  const categoryLabel =
    category === 'flow' ? tFlow('categoryFlow') : tFlow('categoryAction');

  return (
    <div
      className={cn(
        'group cursor-pointer rounded-md border border-l-[3px] border-border/60 bg-background shadow-[0_1px_2px_rgba(0,0,0,0.035)] transition-[background-color,border-color,box-shadow]',
        colorCls,
        category === 'flow' && 'border-border/80 bg-purple-500/[0.025]',
        selected && 'bg-accent/25 ring-2 ring-primary/35',
        isPickTarget &&
          'shadow-[0_0_0_1px_rgba(245,158,11,0.35)] ring-2 ring-amber-500/80',
        coordPickActive &&
          'shadow-[0_0_0_1px_rgba(14,165,233,0.35)] ring-2 ring-sky-500/75',
        reorderControls && 'bg-accent/10 ring-1 ring-primary/15'
      )}
      style={{ contain: 'layout style' }}
      onClick={onClick}
    >
      {isPickTarget && (
        <div className='flex items-center gap-1.5 border-b border-amber-400/30 bg-amber-50/80 px-2.5 py-1 dark:bg-amber-950/20'>
          <Crosshair size={10} className='shrink-0 text-amber-600' />
          <span className='text-[10px] text-amber-800 dark:text-amber-300'>
            {tField('selectorPickHint')}
          </span>
        </div>
      )}
      {coordPickActive === 'tap_point' && (
        <div className='flex items-center gap-1.5 border-b border-sky-400/40 bg-sky-50/90 px-2.5 py-1 dark:bg-sky-950/25'>
          <MousePointerClick
            size={10}
            className='shrink-0 text-sky-700 dark:text-sky-400'
          />
          <span className='text-[10px] text-sky-900 dark:text-sky-200'>
            {tField('tapCoordsHint')}
          </span>
        </div>
      )}
      {coordPickActive === 'swipe_segment' && (
        <div className='flex items-center gap-1.5 border-b border-sky-400/40 bg-sky-50/90 px-2.5 py-1 dark:bg-sky-950/25'>
          <Move size={10} className='shrink-0 text-sky-700 dark:text-sky-400' />
          <span className='text-[10px] text-sky-900 dark:text-sky-200'>
            {tField('swipeCoordsHint')}
          </span>
        </div>
      )}
      <div className='flex items-center gap-2.5 px-2.5 py-2 hover:bg-accent/40'>
        <span
          className={cn(
            'flex size-8 shrink-0 items-center justify-center rounded-md ring-1 ring-inset',
            category === 'flow'
              ? 'bg-purple-500/10 text-purple-600 ring-purple-500/20 dark:text-purple-400'
              : 'bg-blue-500/10 text-blue-600 ring-blue-500/20 dark:text-blue-400'
          )}
        >
          {runState === 'running' ? (
            <Loader2 size={14} className='animate-spin text-primary' />
          ) : runState === 'ok' ? (
            <CheckCircle2 size={14} className='text-emerald-500' />
          ) : runState === 'error' ? (
            <XCircle size={14} className='text-red-500' />
          ) : (
            <StepIcon type={step.type} size={14} />
          )}
        </span>

        <div className='min-w-0 flex-1 overflow-hidden'>
          <div className='flex flex-wrap items-center gap-1.5'>
            <span className='text-xs font-semibold leading-tight text-foreground'>
              {typeName}
            </span>
            <span
              className={cn(
                'rounded-md px-1.5 py-px text-[9px] font-medium',
                category === 'flow'
                  ? 'bg-purple-500/10 text-purple-700 dark:text-purple-300'
                  : 'bg-muted text-muted-foreground'
              )}
            >
              {categoryLabel}
            </span>
            {configurationStatus.state !== 'complete' && (
              <span
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-1.5 py-px text-[9px] font-medium',
                  configurationStatus.state === 'missing'
                    ? 'bg-destructive/10 text-destructive'
                    : 'bg-amber-500/10 text-amber-700 dark:text-amber-300'
                )}
                title={tConfig(
                  configurationStatus.state === 'missing'
                    ? 'cardMissingTitle'
                    : 'cardWarningTitle',
                  { count: configurationIssueCount }
                )}
              >
                <AlertTriangle size={9} />
                {tConfig(
                  configurationStatus.state === 'missing'
                    ? 'cardMissing'
                    : 'cardWarning',
                  { count: configurationIssueCount }
                )}
              </span>
            )}
            {variableIssueCount > 0 && (
              <span
                className={cn(
                  'inline-flex items-center gap-1 rounded-md px-1.5 py-px text-[9px] font-medium',
                  variableCriticalIssueCount > 0
                    ? 'bg-destructive/10 text-destructive'
                    : 'bg-amber-500/10 text-amber-700 dark:text-amber-300'
                )}
                title={tLineage('cardWarningTitle', {
                  count: variableIssueCount
                })}
              >
                <AlertTriangle size={9} />
                {variableCriticalIssueCount > 0
                  ? tLineage('cardCritical', {
                      count: variableIssueCount,
                      critical: variableCriticalIssueCount
                    })
                  : tLineage('cardWarning', { count: variableIssueCount })}
              </span>
            )}
            {!title && selectorBadge && (
              <span className='rounded-md bg-muted px-1.5 py-px font-mono text-[9px] text-muted-foreground'>
                {selectorBadge}
              </span>
            )}
          </div>

          {secondRowMain && (
            <p
              className={cn(
                'mt-0.5 truncate text-[12px] leading-snug',
                title
                  ? 'font-medium text-foreground'
                  : runScenarioEmptyHint
                    ? 'text-muted-foreground'
                    : 'text-foreground/85'
              )}
              title={secondRowMain}
            >
              {secondRowMain}
            </p>
          )}

          {(postFlow.isPost || postFlow.isLike || postFlow.isComment) && (
            <p className='mt-0.5 truncate text-[10px] text-muted-foreground'>
              {postFlow.isPost
                ? tPostFlow('findPostOutcome')
                : postFlow.isLike
                  ? tPostFlow('likePostOutcome')
                  : tPostFlow('commentPostOutcome')}
            </p>
          )}

          {description && (
            <p className='mt-0.5 truncate text-[10px] italic text-muted-foreground'>
              {description}
            </p>
          )}
        </div>

        {step.type === 'tap_image' ? (
          <TapImageThumb step={step} />
        ) : (
          (() => {
            const imgSrc = step.type === 'tap' ? getTapStepImage(step) : '';
            return imgSrc ? (
              // eslint-disable-next-line @next/next/no-img-element -- inline step screenshots may be data URLs.
              <img
                src={imgSrc}
                alt=''
                loading='lazy'
                decoding='async'
                className='h-12 w-8 shrink-0 rounded border border-border/40 object-cover object-top'
              />
            ) : null;
          })()
        )}

        <div className='flex shrink-0 items-center gap-0.5'>
          {reorderControls && (
            <span className='mr-1 flex items-center overflow-hidden rounded-md border border-border/70 bg-background shadow-sm'>
              <button
                type='button'
                className='flex size-6 items-center justify-center text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35'
                disabled={!reorderControls.canMoveUp}
                onClick={(e) => {
                  e.stopPropagation();
                  reorderControls.onMoveUp();
                }}
                aria-label={tField('moveStepUp')}
                title={tField('moveStepUp')}
              >
                <ChevronUp size={13} />
              </button>
              <span className='h-4 w-px bg-border/70' aria-hidden />
              <button
                type='button'
                className='flex size-6 items-center justify-center text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:cursor-not-allowed disabled:opacity-35'
                disabled={!reorderControls.canMoveDown}
                onClick={(e) => {
                  e.stopPropagation();
                  reorderControls.onMoveDown();
                }}
                aria-label={tField('moveStepDown')}
                title={tField('moveStepDown')}
              >
                <ChevronDown size={13} />
              </button>
            </span>
          )}
          {onTogglePickTapCoords && (
            <button
              type='button'
              className={cn(
                'shrink-0 rounded-md p-1 transition-all',
                coordPickActive === 'tap_point'
                  ? 'bg-sky-500/25 text-sky-800 dark:text-sky-300'
                  : 'opacity-0 hover:bg-sky-500/15 hover:text-sky-800 group-hover:opacity-100 dark:hover:text-sky-300'
              )}
              onClick={(e) => {
                e.stopPropagation();
                onTogglePickTapCoords();
              }}
              aria-label={tField('pickTapCoords')}
              title={tField('tapMirrorForCoords')}
            >
              <MousePointerClick size={12} />
            </button>
          )}
          {onTogglePickSwipeCoords && (
            <button
              type='button'
              className={cn(
                'shrink-0 rounded-md p-1 transition-all',
                coordPickActive === 'swipe_segment'
                  ? 'bg-sky-500/25 text-sky-800 dark:text-sky-300'
                  : 'opacity-0 hover:bg-sky-500/15 hover:text-sky-800 group-hover:opacity-100 dark:hover:text-sky-300'
              )}
              onClick={(e) => {
                e.stopPropagation();
                onTogglePickSwipeCoords();
              }}
              aria-label={tField('pickSwipeCoords')}
              title={tField('swipeMirrorForSegment')}
            >
              <Move size={12} />
            </button>
          )}
          {onTogglePickSelector && (
            <button
              type='button'
              className={cn(
                'shrink-0 rounded-md p-1 transition-all',
                isPickTarget
                  ? 'bg-amber-500/20 text-amber-700 dark:text-amber-300'
                  : 'opacity-0 hover:bg-amber-500/15 hover:text-amber-700 group-hover:opacity-100'
              )}
              onClick={(e) => {
                e.stopPropagation();
                onTogglePickSelector();
              }}
              aria-label={tField('pickSelectorFromScreen')}
              title={tField('pickSelectorFromMirror')}
            >
              <Crosshair size={12} />
            </button>
          )}
          {onRun && runState !== 'running' && (
            <button
              type='button'
              className={cn(
                'shrink-0 rounded-md p-1 transition-opacity hover:bg-primary/10 hover:text-primary',
                compact ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
              )}
              onClick={(e) => {
                e.stopPropagation();
                onRun();
              }}
              aria-label={tField('runStep')}
              title={tField('runStepOnDevice')}
            >
              <Play size={12} />
            </button>
          )}
          {onStopInlineRun && runState === 'running' && (
            <button
              type='button'
              className='shrink-0 rounded-md p-1 hover:bg-destructive/15 hover:text-destructive'
              onClick={(e) => {
                e.stopPropagation();
                onStopInlineRun();
              }}
              aria-label={tField('stopTestRun')}
              title={tField('stopTestRun')}
            >
              <Square size={12} fill='currentColor' />
            </button>
          )}
          <button
            type='button'
            className='shrink-0 rounded-md p-1 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100'
            onClick={(e) => {
              e.stopPropagation();
              onRemove();
            }}
            aria-label={tField('deleteStep')}
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>
    </div>
  );
}
