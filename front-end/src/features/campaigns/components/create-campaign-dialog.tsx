'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useCampaigns, useCreateCampaign } from '../hooks/use-campaigns';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { VariableEditor } from '@/components/variable-editor';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { useRouter } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { toast } from 'sonner';
import { mergeScenarioVariables } from '@/lib/scenario-variables';
import { useOrgScenarioBodies } from '@/features/org-scenarios/hooks/use-org-scenarios';
import { Plus, Layers, FileText, Variable, Library } from 'lucide-react';
import { useTranslations } from 'next-intl';
import { formatFarmApiError } from '@/lib/format-farm-api-error';
import { cn } from '@/lib/utils';
import { CampaignOrgScenarioPicker } from './campaign-org-scenario-picker';
import {
  CampaignAccountBindingFields,
  campaignBindingToPayload,
  type CampaignAccountBindingValue
} from './campaign-account-binding-fields';

type FormData = {
  name: string;
  description?: string;
};

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
  const [tags, setTags] = useState('');
  const [selectedScenarioIds, setSelectedScenarioIds] = useState<string[]>(
    preselectedScenarioIds
  );
  const bodyQueries = useOrgScenarioBodies(selectedScenarioIds, open);
  const lastMergedSelectionRef = useRef<string>('');

  useEffect(() => {
    if (!initialOpen) return;
    setOpen(true);
    if (preselectedScenarioIds.length) {
      setSelectedScenarioIds(preselectedScenarioIds);
    }
  }, [initialOpen, preselectedScenarioIds]);

  useEffect(() => {
    if (preselectedScenarioIds.length) {
      setSelectedScenarioIds(preselectedScenarioIds);
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
      setVariables({});
      return;
    }
    if (selectionKey === lastMergedSelectionRef.current) return;
    const pending = selectedScenarioIds.some(
      (_id, index) => bodyQueries[index]?.isLoading
    );
    if (pending) return;
    const layers = bodyQueries.map((query) => {
      const body = query.data?.body_json;
      if (!body || typeof body !== 'object') return {};
      return (body as Record<string, unknown>).variables as
        | Record<string, unknown>
        | undefined;
    });
    setVariables(mergeScenarioVariables(...layers) as Record<string, any>);
    lastMergedSelectionRef.current = selectionKey;
  }, [open, selectedScenarioIds, scenarioBodiesKey, bodyQueries]);

  const [accountBinding, setAccountBinding] =
    useState<CampaignAccountBindingValue>({
      mode: 'none',
      accountGroupId: '',
      scenarioAccountId: ''
    });
  const { mutate, isPending, error } = useCreateCampaign();
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors }
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const handleOpenChange = (next: boolean) => {
    setOpen(next);
    if (next) {
      setSelectedScenarioIds(preselectedScenarioIds);
      reset({
        name: defaultCampaignName ?? '',
        description: ''
      });
      setVariables({});
      setTags('');
      setAccountBinding({
        mode: 'none',
        accountGroupId: '',
        scenarioAccountId: ''
      });
      lastMergedSelectionRef.current = '';
    }
  };

  const effectiveScenarioIds =
    selectedScenarioIds.length > 0
      ? selectedScenarioIds
      : preselectedScenarioIds;

  const onSubmit = (data: FormData) => {
    if (!effectiveScenarioIds.length) {
      toast.error(t('libraryScenarioRequired'));
      return;
    }
    mutate(
      {
        name: data.name,
        description: data.description,
        vars: Object.keys(variables).length ? variables : {},
        tags: tags
          .split(',')
          .map((tag) => tag.trim())
          .filter(Boolean),
        scenario_refs: effectiveScenarioIds.map((scenario_id) => ({
          scenario_id
        })),
        ...campaignBindingToPayload(accountBinding)
      },
      {
        onSuccess: (created) => {
          reset();
          setVariables({});
          setTags('');
          setSelectedScenarioIds(preselectedScenarioIds);
          setAccountBinding({
            mode: 'none',
            accountGroupId: '',
            scenarioAccountId: ''
          });
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

      <DialogContent className='flex max-h-[92vh] min-w-[min(100%-2rem,720px)] max-w-3xl flex-col gap-0 overflow-y-auto p-0 sm:w-full'>
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

        <form onSubmit={handleSubmit(onSubmit)}>
          <div className='space-y-5 px-5 py-5'>
            <Section icon={FileText} title='Thông tin cơ bản'>
              <div className='space-y-3'>
                <div className='space-y-1.5'>
                  <Label className='text-xs'>{t('nameLabel')}</Label>
                  <Input
                    placeholder={t('namePlaceholder')}
                    className={cn('h-9', errors.name && 'border-destructive')}
                    {...register('name')}
                  />
                  {errors.name && (
                    <p className='text-[11px] text-destructive'>
                      {errors.name.message}
                    </p>
                  )}
                </div>
                <div className='space-y-1.5'>
                  <Label className='text-xs'>{t('descriptionLabel')}</Label>
                  <Textarea
                    placeholder={t('descriptionPlaceholder')}
                    className='min-h-[60px] resize-none text-sm'
                    {...register('description')}
                  />
                </div>
              </div>
            </Section>

            <hr className='border-border' />
            <Section icon={Library} title={t('libraryScenariosLabel')}>
              <CampaignOrgScenarioPicker
                selectedIds={selectedScenarioIds}
                onSelectedIdsChange={setSelectedScenarioIds}
              />
            </Section>
            <hr className='border-border' />
            <Section icon={Variable} title={t('tagsLabel')}>
              <Input
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder={t('tagsPlaceholder')}
              />
            </Section>
            <hr className='border-border' />
            <Section icon={Variable} title={t('variablesLabel')}>
              <p className='mb-2 text-[11px] text-muted-foreground'>
                {t('libraryVariablesHint')}
              </p>
              <VariableEditor
                variables={variables}
                onChange={setVariables}
                allowAdd={false}
                lockKeys
                allowRemove={false}
                disabled={effectiveScenarioIds.length === 0}
              />
            </Section>
            <hr className='border-border' />
            <Section icon={Layers} title={t('accountBindingSection')}>
              <p className='mb-2 text-[11px] text-muted-foreground'>
                {t('libraryAccountHint')}
              </p>
              <CampaignAccountBindingFields
                value={accountBinding}
                onChange={setAccountBinding}
              />
            </Section>
          </div>

          <div className='border-t bg-muted/30 px-5 py-3'>
            {error && (
              <p className='mb-2 text-[11px] text-destructive'>
                {formatFarmApiError(error, t('createFailed'))}
              </p>
            )}
            <div className='flex justify-end gap-2'>
              <Button
                type='button'
                variant='ghost'
                size='sm'
                onClick={() => handleOpenChange(false)}
                disabled={isPending}
              >
                Huỷ
              </Button>
              <Button
                type='submit'
                size='sm'
                disabled={isPending || effectiveScenarioIds.length === 0}
              >
                {isPending ? t('creating') : t('submit')}
              </Button>
            </div>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
