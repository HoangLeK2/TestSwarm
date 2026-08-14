'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useCampaigns, useCreateCampaign } from '../hooks/use-campaigns';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Separator } from '@/components/ui/separator';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { VariableEditor } from '@/components/variable-editor';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode
} from 'react';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { toast } from 'sonner';
import { mergeScenarioVariables } from '@/lib/scenario-variables';
import { useOrgScenarioBodies } from '@/features/org-scenarios/hooks/use-org-scenarios';
import {
  ArrowLeft,
  ArrowRight,
  FileText,
  Layers,
  Library,
  Plus,
  Settings2,
  Variable,
  Wrench
} from 'lucide-react';
import { useTranslations } from 'next-intl';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { cn } from '@/lib/utils';
import { CampaignOrgScenarioPicker } from './campaign-org-scenario-picker';
import { RecoveryPolicyEditor } from './recovery-policy-editor';
import type { CampaignScenarioRefIn, RecoveryPolicy } from '../types';
import { normalizeCampaignScenarioRefs, scenarioRefRunCount } from '../types';
import { ContinuousCrawlSettings } from './continuous-crawl-settings';
import {
  campaignVariablesForEditor,
  mergeCampaignEditorVariables
} from '../lib/continuous-crawl-monitor';

type FormData = {
  name: string;
  description?: string;
};

const createSteps = ['basics', 'main', 'recovery', 'settings'] as const;
type CreateStep = (typeof createSteps)[number];

function Section({
  icon: Icon,
  title,
  hint,
  children
}: {
  icon: React.ElementType;
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <div className='space-y-3'>
      <div className='flex items-center gap-2'>
        <Icon size={13} className='shrink-0 text-muted-foreground' />
        <span className='text-xs font-semibold text-foreground'>{title}</span>
        {hint && (
          <span className='text-[10px] text-muted-foreground'>{hint}</span>
        )}
      </div>
      <div className='pl-5'>{children}</div>
    </div>
  );
}

export function CreateCampaignDialog({
  initialOpen = false,
  preselectedScenarioIds = [],
  trigger,
  defaultCampaignName
}: {
  initialOpen?: boolean;
  /** @deprecated Classic create removed; kept for call-site compat. */
  initialMode?: 'classic' | 'library';
  preselectedScenarioIds?: string[];
  /** Custom open trigger; defaults to “New campaign” button. */
  trigger?: ReactNode;
  /** Prefill campaign name (e.g. from scenario library). */
  defaultCampaignName?: string;
  /** @deprecated Library mode is always used. */
  lockLibraryMode?: boolean;
} = {}) {
  const t = useTranslations('campaignsFeature.createDialog');
  const router = useRouter();
  const { data: campaigns } = useCampaigns();
  const existingNames = new Set(
    (campaigns ?? [])
      .map((c) => (c.name ?? '').trim().toLowerCase())
      .filter(Boolean)
  );
  const schema = z.object({
    name: z
      .string()
      .min(1, t('nameRequired'))
      .refine(
        (v) => !existingNames.has(v.trim().toLowerCase()),
        t('nameUnique')
      ),
    description: z.string().optional()
  });
  const [open, setOpen] = useState(false);
  const [variables, setVariables] = useState<Record<string, any>>({});
  const variablesRef = useRef<Record<string, any>>({});
  const userEditedVariablesRef = useRef(false);
  const [tags, setTags] = useState('');
  const [recoveryPolicy, setRecoveryPolicy] = useState<RecoveryPolicy>({});
  const [selectedScenarioRefs, setSelectedScenarioRefs] = useState<
    CampaignScenarioRefIn[]
  >(
    normalizeCampaignScenarioRefs(
      preselectedScenarioIds.map((scenario_id) => ({ scenario_id }))
    )
  );
  const selectedScenarioIds = useMemo(
    () => selectedScenarioRefs.map((ref) => ref.scenario_id),
    [selectedScenarioRefs]
  );
  const [currentStep, setCurrentStep] = useState<CreateStep>('basics');
  const bodyQueries = useOrgScenarioBodies(selectedScenarioIds, open);
  const lastMergedSelectionRef = useRef<string>('');

  const replaceVariables = useCallback((next: Record<string, any>) => {
    variablesRef.current = next;
    setVariables(next);
  }, []);

  const handleVariablesChange = useCallback(
    (next: Record<string, any>) => {
      userEditedVariablesRef.current = true;
      replaceVariables(next);
    },
    [replaceVariables]
  );

  const handleSelectedScenarioRefsChange = useCallback(
    (refs: CampaignScenarioRefIn[]) => {
      userEditedVariablesRef.current = false;
      lastMergedSelectionRef.current = '';
      setSelectedScenarioRefs(normalizeCampaignScenarioRefs(refs));
      replaceVariables({});
    },
    [replaceVariables]
  );

  useEffect(() => {
    if (!initialOpen) return;
    setOpen(true);
    if (preselectedScenarioIds.length) {
      setSelectedScenarioRefs(
        normalizeCampaignScenarioRefs(
          preselectedScenarioIds.map((scenario_id) => ({ scenario_id }))
        )
      );
    }
  }, [initialOpen, preselectedScenarioIds]);

  useEffect(() => {
    if (preselectedScenarioIds.length) {
      setSelectedScenarioRefs(
        normalizeCampaignScenarioRefs(
          preselectedScenarioIds.map((scenario_id) => ({ scenario_id }))
        )
      );
    }
  }, [preselectedScenarioIds]);

  const scenarioBodiesKey = bodyQueries
    .map((query) => {
      const body = query.data?.body_json;
      if (!body || typeof body !== 'object') return '';
      return JSON.stringify((body as Record<string, unknown>).variables ?? {});
    })
    .join('|');

  useEffect(() => {
    if (!open) {
      lastMergedSelectionRef.current = '';
      return;
    }
    const selectionKey = selectedScenarioIds.join(',');
    if (!selectedScenarioIds.length) {
      lastMergedSelectionRef.current = '';
      userEditedVariablesRef.current = false;
      if (Object.keys(variablesRef.current).length) {
        replaceVariables({});
      }
      return;
    }
    if (selectionKey === lastMergedSelectionRef.current) return;
    const pending = selectedScenarioIds.some(
      (_id, index) => bodyQueries[index]?.isLoading
    );
    if (pending) return;
    if (userEditedVariablesRef.current) {
      lastMergedSelectionRef.current = selectionKey;
      return;
    }
    const layers = bodyQueries.map((query) => {
      const body = query.data?.body_json;
      if (!body || typeof body !== 'object') return {};
      return (body as Record<string, unknown>).variables as
        | Record<string, unknown>
        | undefined;
    });
    replaceVariables(mergeScenarioVariables(...layers) as Record<string, any>);
    lastMergedSelectionRef.current = selectionKey;
  }, [
    open,
    selectedScenarioIds,
    scenarioBodiesKey,
    bodyQueries,
    replaceVariables
  ]);

  const { mutate, isPending, error } = useCreateCampaign();
  const {
    register,
    handleSubmit,
    reset,
    trigger: validateForm,
    formState: { errors }
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) {
      setSelectedScenarioRefs(
        normalizeCampaignScenarioRefs(
          preselectedScenarioIds.map((scenario_id) => ({ scenario_id }))
        )
      );
      reset({
        name: defaultCampaignName ?? '',
        description: ''
      });
      userEditedVariablesRef.current = false;
      replaceVariables({});
      setTags('');
      setRecoveryPolicy({});
      setCurrentStep('basics');
      lastMergedSelectionRef.current = '';
    }
  };

  const preselectedScenarioRefs = useMemo(
    () =>
      normalizeCampaignScenarioRefs(
        preselectedScenarioIds.map((scenario_id) => ({ scenario_id }))
      ),
    [preselectedScenarioIds]
  );
  const effectiveScenarioRefs = useMemo(
    () =>
      selectedScenarioRefs.length > 0
        ? selectedScenarioRefs
        : preselectedScenarioRefs,
    [preselectedScenarioRefs, selectedScenarioRefs]
  );
  const effectiveScenarioIds = useMemo(
    () => effectiveScenarioRefs.map((ref) => ref.scenario_id),
    [effectiveScenarioRefs]
  );
  const effectiveRunCount = scenarioRefRunCount(effectiveScenarioRefs);

  const currentStepIndex = createSteps.indexOf(currentStep);
  const isLastStep = currentStepIndex === createSteps.length - 1;
  const stepItems: Array<{
    id: CreateStep;
    label: string;
    hint: string;
    icon: React.ElementType;
  }> = [
    {
      id: 'basics',
      label: t('stepBasics'),
      hint: t('stepBasicsHint'),
      icon: FileText
    },
    {
      id: 'main',
      label: t('stepMainScenarios'),
      hint: t('stepMainScenariosHint'),
      icon: Library
    },
    {
      id: 'recovery',
      label: t('stepRecovery'),
      hint: t('stepRecoveryHint'),
      icon: Wrench
    },
    {
      id: 'settings',
      label: t('stepSettings'),
      hint: t('stepSettingsHint'),
      icon: Settings2
    }
  ];

  const goToPreviousStep = () => {
    setCurrentStep(createSteps[Math.max(0, currentStepIndex - 1)] ?? 'basics');
  };

  const goToNextStep = async () => {
    if (currentStep === 'basics') {
      const valid = await validateForm('name');
      if (!valid) return;
    }
    if (currentStep === 'main' && effectiveScenarioIds.length === 0) {
      toast.error(t('libraryScenarioRequired'));
      return;
    }
    setCurrentStep(
      createSteps[Math.min(createSteps.length - 1, currentStepIndex + 1)] ??
        'settings'
    );
  };

  const onSubmit = (data: FormData) => {
    if (!effectiveScenarioIds.length) {
      toast.error(t('libraryScenarioRequired'));
      return;
    }
    mutate(
      {
        name: data.name,
        description: data.description,
        vars: Object.keys(variablesRef.current).length
          ? variablesRef.current
          : {},
        tags: tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
        scenario_refs: effectiveScenarioRefs,
        recovery_policy: recoveryPolicy
      },
      {
        onSuccess: (created) => {
          reset();
          userEditedVariablesRef.current = false;
          replaceVariables({});
          setTags('');
          setRecoveryPolicy({});
          setSelectedScenarioRefs(
            normalizeCampaignScenarioRefs(
              preselectedScenarioIds.map((scenario_id) => ({ scenario_id }))
            )
          );
          setCurrentStep('basics');
          setOpen(false);
          toast.success(t('createSuccess'));
          if (created?.id) {
            router.push(ROUTES.CAMPAIGNS.DETAIL(created.id));
          }
        },
        onError: (err: unknown) => {
          toast.error(formatFarmApiError(err, t('createFailed')));
        }
      }
    );
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button size='sm'>
            <Plus size={16} className='mr-1' />
            {t('trigger')}
          </Button>
        )}
      </DialogTrigger>

      <DialogContent className='flex max-h-[92vh] min-w-[min(100%-2rem,720px)] max-w-5xl flex-col gap-0 overflow-hidden p-0 sm:w-full'>
        <DialogHeader className='border-b px-5 py-4'>
          <div className='flex items-center gap-2'>
            <Layers size={15} className='text-primary' />
            <DialogTitle className='text-sm font-semibold'>
              {t('title')}
            </DialogTitle>
          </div>
          <p className='mt-0.5 text-[11px] text-muted-foreground'>
            {t('subtitle')}
          </p>
        </DialogHeader>

        <form
          onSubmit={handleSubmit(onSubmit)}
          className='flex min-h-0 flex-1 flex-col'
        >
          <Tabs
            value={currentStep}
            onValueChange={(value) => setCurrentStep(value as CreateStep)}
            className='min-h-0 flex-1 gap-0'
          >
            <div className='shrink-0 border-b px-5 py-3'>
              <TabsList className='grid h-auto w-full grid-cols-2 gap-1.5 bg-muted/60 p-1.5 lg:grid-cols-4'>
                {stepItems.map((step, index) => {
                  return (
                    <TabsTrigger
                      key={step.id}
                      value={step.id}
                      className='flex h-auto w-full min-w-0 flex-col items-start justify-start gap-1 whitespace-normal rounded-md px-2.5 py-2 text-left lg:px-3'
                    >
                      <span className='flex w-full min-w-0 items-center gap-2'>
                        <span
                          className={cn(
                            'flex size-5 shrink-0 items-center justify-center rounded-full border text-[10px] font-semibold tabular-nums',
                            currentStep === step.id
                              ? 'border-primary bg-primary text-primary-foreground'
                              : 'border-border text-muted-foreground'
                          )}
                        >
                          {index + 1}
                        </span>
                        <span className='min-w-0 text-xs font-medium leading-snug'>
                          {step.label}
                        </span>
                      </span>
                      <span className='w-full pl-7 text-[11px] font-normal leading-snug text-muted-foreground'>
                        {step.hint}
                      </span>
                    </TabsTrigger>
                  );
                })}
              </TabsList>
            </div>

            <div className='min-h-0 flex-1 overflow-y-auto'>
              <div className='px-5 py-5'>
                <TabsContent value='basics' className='m-0'>
                  <Section icon={FileText} title={t('basicInfoSection')}>
                    <div className='space-y-3'>
                      <div className='space-y-1.5'>
                        <Label className='text-xs'>{t('nameLabel')}</Label>
                        <Input
                          placeholder={t('namePlaceholder')}
                          className={cn(
                            'h-9',
                            errors.name && 'border-destructive'
                          )}
                          {...register('name')}
                        />
                        {errors.name && (
                          <p className='text-[11px] text-destructive'>
                            {errors.name.message}
                          </p>
                        )}
                      </div>
                      <div className='space-y-1.5'>
                        <Label className='text-xs'>
                          {t('descriptionLabel')}
                        </Label>
                        <Textarea
                          placeholder={t('descriptionPlaceholder')}
                          className='min-h-[96px] resize-none text-sm'
                          {...register('description')}
                        />
                      </div>
                    </div>
                  </Section>
                </TabsContent>

                <TabsContent value='main' className='m-0'>
                  <Section
                    icon={Library}
                    title={t('mainScenariosLabel')}
                    hint={t('mainScenariosHint')}
                  >
                    <CampaignOrgScenarioPicker
                      selectedRefs={selectedScenarioRefs}
                      onSelectedRefsChange={handleSelectedScenarioRefsChange}
                      scenarioFilter='regular'
                      showRepeatConfig
                    />
                    {effectiveScenarioRefs.length > 0 ? (
                      <p className='mt-2 text-[11px] text-muted-foreground'>
                        {t('repeatSummary', {
                          scenarios: effectiveScenarioRefs.length,
                          runs: effectiveRunCount
                        })}
                      </p>
                    ) : null}
                  </Section>
                </TabsContent>

                <TabsContent value='recovery' className='m-0'>
                  <Section
                    icon={Wrench}
                    title={t('recoveryScenariosLabel')}
                    hint={t('recoveryScenariosHint')}
                  >
                    <RecoveryPolicyEditor
                      value={recoveryPolicy}
                      onChange={setRecoveryPolicy}
                      scenarioFilter='recovery'
                    />
                  </Section>
                </TabsContent>

                <TabsContent value='settings' className='m-0'>
                  <div className='space-y-5'>
                    <Section icon={Settings2} title={t('automationLabel')}>
                      <ContinuousCrawlSettings
                        variables={variables}
                        onChange={handleVariablesChange}
                        disabled={effectiveScenarioIds.length === 0}
                      />
                    </Section>
                    <Separator />
                    <Section icon={Variable} title={t('tagsLabel')}>
                      <Input
                        value={tags}
                        onChange={(e) => setTags(e.target.value)}
                        placeholder={t('tagsPlaceholder')}
                      />
                    </Section>
                    <Separator />
                    <Section icon={Variable} title={t('variablesLabel')}>
                      <p className='mb-2 text-[11px] text-muted-foreground'>
                        {t('libraryVariablesHint')}
                      </p>
                      <VariableEditor
                        variables={campaignVariablesForEditor(variables)}
                        onChange={(next) =>
                          handleVariablesChange(
                            mergeCampaignEditorVariables(variables, next)
                          )
                        }
                        allowAdd={false}
                        lockKeys
                        allowRemove={false}
                        disabled={effectiveScenarioIds.length === 0}
                      />
                    </Section>
                    <Separator />
                    <Section icon={Layers} title={t('accountBindingSection')}>
                      <p className='mb-2 text-[11px] text-muted-foreground'>
                        {t('libraryAccountHint')}
                      </p>
                    </Section>
                  </div>
                </TabsContent>
              </div>
            </div>
          </Tabs>

          <div className='shrink-0 border-t bg-muted/30 px-5 py-3'>
            {error && (
              <p className='mb-2 text-[11px] text-destructive'>
                {formatFarmApiError(error, t('createFailed'))}
              </p>
            )}
            <div className='flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between'>
              <p className='text-[11px] text-muted-foreground'>
                {t('stepProgress', {
                  current: currentStepIndex + 1,
                  total: createSteps.length
                })}
              </p>
              <div className='flex justify-end gap-2'>
                <Button
                  type='button'
                  variant='ghost'
                  size='sm'
                  onClick={() => handleOpenChange(false)}
                  disabled={isPending}
                >
                  {t('cancel')}
                </Button>
                {currentStepIndex > 0 ? (
                  <Button
                    type='button'
                    variant='outline'
                    size='sm'
                    onClick={goToPreviousStep}
                    disabled={isPending}
                    className='gap-1.5'
                  >
                    <ArrowLeft size={14} />
                    {t('back')}
                  </Button>
                ) : null}
                {!isLastStep ? (
                  <Button
                    type='button'
                    size='sm'
                    onClick={() => void goToNextStep()}
                    disabled={isPending}
                    className='gap-1.5'
                  >
                    {t('next')}
                    <ArrowRight size={14} />
                  </Button>
                ) : null}
                {isLastStep ? (
                  <Button
                    type='submit'
                    size='sm'
                    disabled={isPending || effectiveScenarioIds.length === 0}
                  >
                    {isPending ? t('creating') : t('submit')}
                  </Button>
                ) : null}
              </div>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
