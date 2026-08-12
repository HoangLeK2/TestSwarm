'use client';

import { useEffect, useMemo, useState } from 'react';
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  Copy,
  Download,
  Play,
  ShieldCheck
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { toast } from 'sonner';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from '@/components/ui/dropdown-menu';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import {
  Sheet,
  SheetContent,
  SheetFooter,
  SheetHeader,
  SheetTitle
} from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { Can } from '@/features/auth';
import { useUser } from '@/features/auth/hooks/use-auth';
import {
  formatFarmApiError,
  formatFarmApiErrorAsync
} from '@/lib/format-farm-api-error';
import { isSuperadminRole } from '@/lib/nav-access';
import { cn } from '@/lib/utils';
import {
  useExportOrgScenario,
  useOrgScenario,
  useOrgScenarioBody,
  useScenarioTemplateDetail,
  useUpdateOrgScenario,
  useValidateOrgScenario
} from '../hooks/use-org-scenarios';
import type { OrgScenarioOut, OrgScenarioValidationOut } from '../services/api';
import type { ScenarioLibraryItem } from '../lib/scenario-library-item';
import { isSystemTemplateItem } from '../lib/constants';
import { extractPreviewSteps } from '../lib/parse-scenario-body';
import { CloneTemplateDialog } from './clone-template-dialog';
import { CreateCampaignFromScenarioButton } from './create-campaign-from-scenario-button';
import { RunPreviewDialog } from './run-preview-dialog';
import { ImportOrgScenarioDialog } from './import-scenario-dialog';
import { ScenarioBodyPreview } from './scenario-body-preview';

type ValidationIssue = {
  code?: string;
  message?: string;
  location?: string;
};

type DetailT = ReturnType<typeof useTranslations<'orgScenariosFeature.detail'>>;

function scenarioStatusLabel(t: DetailT, status: string): string {
  if (status === 'draft') return t('status.draft');
  if (status === 'active') return t('status.active');
  if (status === 'archived') return t('status.archived');
  return status;
}

function validationStatusLabel(t: DetailT, status: string): string {
  if (status === 'valid') return t('validationStatus.valid');
  if (status === 'invalid') return t('validationStatus.invalid');
  return t('validationStatus.unknown');
}

export function ScenarioDetailSheet({
  item,
  open,
  onOpenChange
}: {
  item: ScenarioLibraryItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations('orgScenariosFeature.detail');
  const router = useRouter();
  const { user } = useUser();
  const isSuperadmin = isSuperadminRole(user?.role);
  const isTemplate = item?.source === 'template';
  const scenarioId = !isTemplate && item ? item.id : '';
  const { data: scenario, isLoading: orgLoading } = useOrgScenario(
    scenarioId,
    open && !isTemplate
  );
  const { data: template, isLoading: templateLoading } =
    useScenarioTemplateDetail(
      isTemplate && item ? item.id : '',
      open && isTemplate
    );
  const { data: bodyData, isLoading: bodyLoading } = useOrgScenarioBody(
    scenarioId,
    open && !isTemplate
  );
  const isLoading = isTemplate ? templateLoading : orgLoading;
  const updateMutation = useUpdateOrgScenario();
  const validateMutation = useValidateOrgScenario();
  const exportMutation = useExportOrgScenario();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [tags, setTags] = useState('');
  const [status, setStatus] = useState<'draft' | 'active' | 'archived'>(
    'draft'
  );
  const [validation, setValidation] = useState<OrgScenarioValidationOut | null>(
    null
  );
  const [previewOpen, setPreviewOpen] = useState(false);
  const [tab, setTab] = useState('info');

  useEffect(() => {
    if (isTemplate && template) {
      setName(item?.name ?? template.name);
      setDescription(template.description ?? '');
      setTags(
        String(template.tags ?? '')
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean)
          .join(', ')
      );
      setValidation(null);
      return;
    }
    if (!scenario) return;
    setName(scenario.name);
    setDescription(scenario.description ?? '');
    setTags((scenario.tags ?? []).join(', '));
    setStatus(
      scenario.status === 'active' || scenario.status === 'archived'
        ? scenario.status
        : 'draft'
    );
    setValidation(null);
  }, [scenario, template, isTemplate, item?.name]);

  const bodyPayload = useMemo(() => {
    if (isTemplate && template) {
      const tpl = template as {
        steps?: unknown[];
        nodes?: unknown[];
        edges?: unknown[];
        variables?: Record<string, unknown>;
      };
      return {
        steps: tpl.steps ?? [],
        nodes: tpl.nodes ?? [],
        edges: tpl.edges ?? [],
        variables: tpl.variables ?? {}
      } as Record<string, unknown>;
    }
    return (bodyData?.body_json ?? scenario?.body_json ?? null) as Record<
      string,
      unknown
    > | null;
  }, [bodyData, scenario, isTemplate, template]);

  const bodyPreview = useMemo(() => {
    if (!bodyPayload) return '{}';
    try {
      return JSON.stringify(bodyPayload, null, 2);
    } catch {
      return '{}';
    }
  }, [bodyPayload]);

  const previewKind = isTemplate
    ? (item?.kind ?? 'sequence')
    : (scenario?.kind ?? item?.kind ?? 'sequence');

  const handleSaveMeta = () => {
    if (!scenarioId) return;
    const nextTags = tags
      .split(',')
      .map((tag) => tag.trim())
      .filter(Boolean);
    updateMutation.mutate(
      {
        scenarioId,
        data: {
          name: name.trim(),
          description: description.trim(),
          tags: nextTags,
          status
        }
      },
      {
        onSuccess: () => toast.success(t('saveSuccess')),
        onError: (error) =>
          toast.error(formatFarmApiError(error, t('saveFailed')))
      }
    );
  };

  const handleValidate = () => {
    if (!scenarioId) return;
    validateMutation.mutate(
      { scenarioId },
      {
        onSuccess: (result) => {
          setValidation(result);
          toast.success(
            t('validateDone', {
              status: validationStatusLabel(t, result.status)
            })
          );
        },
        onError: (error) =>
          toast.error(formatFarmApiError(error, t('validateFailed')))
      }
    );
  };

  const handleExport = (format: 'yaml' | 'json') => {
    if (!scenarioId) return;
    const stepCount = extractPreviewSteps(bodyPayload).length;
    if (stepCount === 0) {
      toast.warning(t('exportEmptyBody'));
    }
    exportMutation.mutate(
      { scenarioId, format },
      {
        onSuccess: (result) => {
          toast.success(
            stepCount > 0
              ? t('exportSuccess')
              : t('exportSuccessMetadataOnly', { size: result?.size ?? 0 })
          );
        },
        onError: async (error) => {
          toast.error(await formatFarmApiErrorAsync(error, t('exportFailed')));
        }
      }
    );
  };

  const handleCopyBody = async () => {
    try {
      await navigator.clipboard.writeText(bodyPreview);
      toast.success(t('copySuccess'));
    } catch {
      toast.error(t('copyFailed'));
    }
  };

  const handleRecordInControl = () => {
    if (!scenarioId) return;
    const returnTo = `${ROUTES.ORG_SCENARIOS.ROOT}?scenario_id=${encodeURIComponent(scenarioId)}`;
    router.push(
      ROUTES.DEVICES.CONTROL_RECORD_EDIT_ORG_SCENARIO(scenarioId, { returnTo })
    );
  };

  const readOnly = isTemplate && !isSuperadmin;
  const displayName =
    item?.name ?? scenario?.name ?? template?.name ?? t('title');
  const detailLoaded = isTemplate ? Boolean(template) : Boolean(scenario);

  const lastValidationStatus =
    scenario?.last_validation_summary &&
    typeof scenario.last_validation_summary === 'object' &&
    scenario.last_validation_summary !== null &&
    'status' in scenario.last_validation_summary
      ? String(
          (scenario.last_validation_summary as { status?: string }).status ?? ''
        )
      : null;

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className='flex w-full flex-col gap-0 overflow-hidden p-0 sm:max-w-3xl'>
        <SheetHeader className='shrink-0 space-y-3 border-b px-6 py-4 pr-12'>
          <div className='flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between'>
            <div className='min-w-0 space-y-1'>
              <SheetTitle className='text-left text-base font-semibold leading-snug'>
                {displayName}
              </SheetTitle>
              {item ? (
                <ScenarioStatusBadges item={item} scenario={scenario} t={t} />
              ) : null}
            </div>
            {!isTemplate && scenarioId && scenario?.status !== 'archived' ? (
              <CreateCampaignFromScenarioButton
                scenarioId={scenarioId}
                scenarioName={scenario?.name}
                isRunnable={scenario?.is_runnable ?? false}
                className='shrink-0'
              />
            ) : null}
          </div>
        </SheetHeader>

        {readOnly ? (
          <div className='shrink-0 border-b px-6 py-3'>
            <Alert>
              <AlertDescription className='text-sm'>
                {t('systemTemplateReadOnly')}
              </AlertDescription>
            </Alert>
          </div>
        ) : null}

        <div className='flex min-h-0 flex-1 flex-col'>
          {isLoading ? (
            <div className='space-y-4 px-6 py-6'>
              <Skeleton className='h-9 w-full rounded-lg' />
              <Skeleton className='h-48 w-full rounded-lg' />
            </div>
          ) : null}

          {detailLoaded && !isLoading ? (
            <Tabs
              value={tab}
              onValueChange={setTab}
              className='flex min-h-0 flex-1 flex-col gap-0'
            >
              <div className='shrink-0 border-b px-6 py-3'>
                <TabsList className='grid h-9 w-full grid-cols-2'>
                  <TabsTrigger value='info'>{t('tabInfo')}</TabsTrigger>
                  <TabsTrigger value='body'>{t('tabBody')}</TabsTrigger>
                </TabsList>
              </div>

              <TabsContent
                value='info'
                className='mt-0 flex min-h-0 flex-1 flex-col data-[state=inactive]:hidden'
              >
                <div className='flex-1 space-y-4 overflow-y-auto px-6 py-4'>
                  <div className='space-y-1.5'>
                    <Label htmlFor='scenario-detail-name'>
                      {t('nameLabel')}
                    </Label>
                    <Input
                      id='scenario-detail-name'
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      disabled={readOnly}
                    />
                  </div>
                  <div className='space-y-1.5'>
                    <Label htmlFor='scenario-detail-desc'>
                      {t('descriptionLabel')}
                    </Label>
                    <Textarea
                      id='scenario-detail-desc'
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      className='min-h-[96px] resize-y'
                      disabled={readOnly}
                    />
                  </div>
                  <div className='space-y-1.5'>
                    <Label htmlFor='scenario-detail-tags'>
                      {t('tagsLabel')}
                    </Label>
                    <Input
                      id='scenario-detail-tags'
                      value={tags}
                      onChange={(e) => setTags(e.target.value)}
                      placeholder={t('tagsPlaceholder')}
                      className='font-mono text-sm'
                      disabled={readOnly}
                    />
                  </div>
                  {!readOnly && !isTemplate ? (
                    <div className='space-y-1.5'>
                      <Label htmlFor='scenario-detail-status'>
                        {t('statusLabel')}
                      </Label>
                      <Select
                        value={status}
                        onValueChange={(value) =>
                          setStatus(value as 'draft' | 'active' | 'archived')
                        }
                      >
                        <SelectTrigger
                          id='scenario-detail-status'
                          className='h-9'
                        >
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent className='z-[10001]'>
                          <SelectItem value='draft'>
                            {t('status.draft')}
                          </SelectItem>
                          <SelectItem value='active'>
                            {t('status.active')}
                          </SelectItem>
                        </SelectContent>
                      </Select>
                      <p className='text-[11px] text-muted-foreground'>
                        {t('statusHint')}
                      </p>
                    </div>
                  ) : null}
                </div>
                <SheetFooter className='shrink-0 gap-2 border-t bg-muted/20 px-6 py-3 sm:justify-end'>
                  {readOnly && item ? (
                    <Can object='scenarios' action='create'>
                      <CloneTemplateDialog template={item} />
                    </Can>
                  ) : isTemplate && isSuperadmin && item ? null : (
                    <Can object='scenarios' action='update'>
                      <Button
                        type='button'
                        size='sm'
                        onClick={handleSaveMeta}
                        disabled={updateMutation.isPending || !name.trim()}
                      >
                        {updateMutation.isPending ? t('saving') : t('saveMeta')}
                      </Button>
                    </Can>
                  )}
                </SheetFooter>
              </TabsContent>

              <TabsContent
                value='body'
                className='mt-0 flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 py-4 data-[state=inactive]:hidden'
              >
                <p className='text-xs text-muted-foreground'>
                  {t('bodyFlowHint')}
                </p>

                <ScenarioBodyActions
                  t={t}
                  scenarioId={scenarioId}
                  isRunnable={
                    isTemplate
                      ? (item?.is_runnable ?? false)
                      : (scenario?.is_runnable ?? false)
                  }
                  readOnly={readOnly || isTemplate}
                  showOrgActions={!isTemplate}
                  onRecord={handleRecordInControl}
                  onRunPreview={() => setPreviewOpen(true)}
                  onValidate={handleValidate}
                  onExport={handleExport}
                  onCopy={handleCopyBody}
                  onImported={() => setValidation(null)}
                  validating={validateMutation.isPending}
                  exporting={exportMutation.isPending}
                />

                {!isTemplate && bodyLoading ? (
                  <Skeleton className='h-[min(45vh,400px)] w-full rounded-lg' />
                ) : (
                  <ScenarioBodyPreview
                    body={bodyPayload}
                    kind={previewKind}
                    rawJson={bodyPreview !== '{}' ? bodyPreview : undefined}
                    importTargetScenarioId={
                      !isTemplate && !readOnly ? scenarioId : undefined
                    }
                    onImported={() => setValidation(null)}
                  />
                )}

                {validation ? (
                  <ValidationAlert validation={validation} t={t} />
                ) : null}

                {lastValidationStatus && !validation ? (
                  <Alert>
                    <ShieldCheck className='size-4' />
                    <AlertTitle className='text-sm'>
                      {t('lastValidation', {
                        status: validationStatusLabel(t, lastValidationStatus)
                      })}
                    </AlertTitle>
                  </Alert>
                ) : null}
              </TabsContent>
            </Tabs>
          ) : null}
        </div>

        {!isTemplate ? (
          <RunPreviewDialog
            open={previewOpen}
            onOpenChange={setPreviewOpen}
            scenarioId={scenarioId}
            scenarioName={scenario?.name}
            disabled={!scenario?.is_runnable}
          />
        ) : null}
      </SheetContent>
    </Sheet>
  );
}

function ScenarioStatusBadges({
  item,
  scenario,
  t
}: {
  item: ScenarioLibraryItem;
  scenario?: OrgScenarioOut;
  t: DetailT;
}) {
  const isSystem = isSystemTemplateItem(item);
  const status = item.status;
  const version = item.scenario_version;
  const runnable = item.is_runnable;
  return (
    <div className='flex flex-wrap items-center gap-1.5 pt-1'>
      {isSystem ? (
        <Badge variant='secondary' className='text-[11px] font-normal'>
          {t('systemTemplateBadge')}
        </Badge>
      ) : null}
      {!isSystem ? (
        <Badge
          variant={status === 'draft' ? 'secondary' : 'default'}
          className='text-[11px] font-normal'
        >
          {scenarioStatusLabel(t, status)}
        </Badge>
      ) : null}
      {!isSystem ? (
        <Badge variant='outline' className='text-[11px] font-normal'>
          {t('versionBadge', { version })}
        </Badge>
      ) : null}
      <Badge
        variant={runnable ? 'default' : 'secondary'}
        className={cn(
          'text-[11px] font-normal',
          runnable && 'border-0 bg-emerald-600 hover:bg-emerald-600'
        )}
      >
        {runnable ? t('runnable') : t('notRunnable')}
      </Badge>
    </div>
  );
}

function ScenarioBodyActions({
  t,
  scenarioId,
  isRunnable,
  readOnly,
  showOrgActions,
  onRecord,
  onRunPreview,
  onValidate,
  onExport,
  onCopy,
  onImported,
  validating,
  exporting
}: {
  t: DetailT;
  scenarioId: string;
  isRunnable: boolean;
  readOnly: boolean;
  showOrgActions: boolean;
  onRecord: () => void;
  onRunPreview: () => void;
  onValidate: () => void;
  onExport: (format: 'yaml' | 'json') => void;
  onCopy: () => void;
  onImported?: () => void;
  validating: boolean;
  exporting: boolean;
}) {
  return (
    <div className='flex flex-wrap items-center gap-2'>
      {showOrgActions && !readOnly && scenarioId ? (
        <Can object='scenarios' action='update'>
          <ImportOrgScenarioDialog
            targetScenarioId={scenarioId}
            onImported={onImported}
            triggerLabel={t('importIntoScenario')}
          />
          <Button type='button' size='sm' variant='outline' onClick={onRecord}>
            {t('recordInControl')}
          </Button>
        </Can>
      ) : null}
      {!readOnly ? (
        <Can object='scenarios' action='update'>
          <Button
            type='button'
            size='sm'
            onClick={onRunPreview}
            disabled={!isRunnable}
          >
            <Play className='size-4' />
            {t('runPreview')}
          </Button>
        </Can>
      ) : null}
      {showOrgActions ? (
        <Button
          type='button'
          size='sm'
          variant='outline'
          onClick={onValidate}
          disabled={validating}
        >
          <ShieldCheck className='size-4' />
          {validating ? t('validating') : t('validate')}
        </Button>
      ) : null}
      <Button type='button' size='sm' variant='outline' onClick={onCopy}>
        <Copy className='size-4' />
        {t('copyBody')}
      </Button>
      {showOrgActions ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type='button'
              size='sm'
              variant='outline'
              disabled={exporting}
            >
              <Download className='size-4' />
              {t('exportMenu')}
              <ChevronDown className='size-3.5 opacity-60' />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align='end'>
            <DropdownMenuItem onClick={() => onExport('yaml')}>
              {t('exportYaml')}
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => onExport('json')}>
              {t('exportJson')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}
    </div>
  );
}

function ValidationAlert({
  validation,
  t
}: {
  validation: OrgScenarioValidationOut;
  t: DetailT;
}) {
  const issues = [
    ...(validation.errors ?? []).map((issue: ValidationIssue) => ({
      ...issue,
      level: 'error' as const
    })),
    ...(validation.warnings ?? []).map((issue: ValidationIssue) => ({
      ...issue,
      level: 'warning' as const
    })),
    ...(validation.infos ?? []).map((issue: ValidationIssue) => ({
      ...issue,
      level: 'info' as const
    }))
  ];

  const isValid = validation.status === 'valid' && issues.length === 0;
  const isInvalid =
    validation.status === 'invalid' || issues.some((i) => i.level === 'error');

  return (
    <Alert variant={isInvalid ? 'destructive' : 'default'}>
      {isValid ? (
        <CheckCircle2 className='size-4 text-emerald-600' />
      ) : (
        <AlertCircle className='size-4' />
      )}
      <AlertTitle>
        {t('validationTitle')}: {validationStatusLabel(t, validation.status)}
      </AlertTitle>
      <AlertDescription>
        {!issues.length ? (
          <p>{t('validationClean')}</p>
        ) : (
          <ul className='mt-2 max-h-48 space-y-2 overflow-y-auto'>
            {issues.map((issue, index) => (
              <li
                key={`${issue.code ?? 'issue'}-${index}`}
                className='rounded-md border border-border/60 bg-background/60 px-2.5 py-2 text-xs'
              >
                <span className='font-medium'>
                  {t(`issueLevel.${issue.level}`)}
                </span>
                : {issue.message}
                {issue.location ? (
                  <span className='mt-1 block font-mono text-[10px] opacity-80'>
                    {issue.location}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </AlertDescription>
    </Alert>
  );
}
