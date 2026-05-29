'use client';

import { useMemo, useState } from 'react';
import { useTranslations } from 'next-intl';
import { FileCode, Search } from 'lucide-react';
import {
  useScenarioTemplates,
  useDeleteScenarioTemplate,
  useDuplicateScenarioTemplate
} from '../../hooks/use-scenario-templates';
import type { ScenarioTemplateOut } from '../../services/api';
import { DataTable } from '@/components/ui/table/data-table';
import { useDataTable } from '@/hooks/use-data-table';
import { CreateTemplateDialog } from '../create-template-dialog';
import { getTemplateColumns } from './columns';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import { useConfirm } from '@/providers/modal-provider';

const CATEGORIES = ['all', 'general', 'facebook', 'tiktok', 'utility'] as const;

function humanizeTechnicalName(name: string) {
  const raw = String(name ?? '').trim();
  if (!raw) return '';
  const spaced = raw
    .replace(/[_\-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  return spaced
    .split(' ')
    .map((w) =>
      w.toUpperCase() === w ? w : w.charAt(0).toUpperCase() + w.slice(1)
    )
    .join(' ');
}

export function TemplateList() {
  const t = useTranslations('scenarioTemplatesFeature.list');
  const tCommon = useTranslations('common');
  const confirm = useConfirm();
  const { data: templates, isLoading, error } = useScenarioTemplates();
  const deleteMutation = useDeleteScenarioTemplate();
  const duplicateMutation = useDuplicateScenarioTemplate();
  const [category, setCategory] = useState<string>('all');
  const [search, setSearch] = useState('');

  const filtered = useMemo(() => {
    let list = templates ?? [];
    if (category !== 'all') {
      list = list.filter((tpl) => tpl.category === category);
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      list = list.filter(
        (tpl) =>
          tpl.name.toLowerCase().includes(q) ||
          humanizeTechnicalName(tpl.name).toLowerCase().includes(q) ||
          tpl.description?.toLowerCase().includes(q) ||
          tpl.tags?.toLowerCase().includes(q)
      );
    }
    return list;
  }, [templates, category, search]);

  const columns = useMemo(
    () =>
      getTemplateColumns(
        t,
        (tpl) => {
          void (async () => {
            const ok = await confirm({
              title: t('delete'),
              description: t('confirmDelete', { name: tpl.name }),
              confirmText: tCommon('confirm'),
              cancelText: tCommon('cancel'),
              confirmVariant: 'destructive',
              zIndex: 10_000
            });
            if (!ok) return;
            deleteMutation.mutate(tpl.id);
          })();
        },
        (tpl) => {
          duplicateMutation.mutate(tpl.id);
        }
      ),
    [t, tCommon, confirm, deleteMutation, duplicateMutation]
  );

  const { table } = useDataTable<ScenarioTemplateOut>({
    data: filtered,
    columns,
    pageCount: 1
  });

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = { all: templates?.length ?? 0 };
    (templates ?? []).forEach((tpl) => {
      counts[tpl.category] = (counts[tpl.category] || 0) + 1;
    });
    return counts;
  }, [templates]);

  return (
    <div className='space-y-6'>
      {isLoading || error ? (
        <div>
          {isLoading && (
            <p className='text-sm text-muted-foreground'>{t('loading')}</p>
          )}
          {error && (
            <p className='text-sm text-destructive'>{t('loadError')}</p>
          )}
        </div>
      ) : (
        <>
          <div className='flex flex-wrap items-center justify-between gap-3'>
            <p className='text-muted-foreground'>
              <span className='font-medium text-foreground'>
                {templates?.length ?? 0}
              </span>{' '}
              {t('countLabel')}
            </p>
            <CreateTemplateDialog />
          </div>

          {/* Category tabs + search */}
          <div className='flex flex-wrap items-center gap-3'>
            <div className='flex gap-1'>
              {CATEGORIES.map((cat) => (
                <button
                  key={cat}
                  onClick={() => setCategory(cat)}
                  className={cn(
                    'rounded-full px-3 py-1 text-xs font-medium transition-colors',
                    category === cat
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-muted text-muted-foreground hover:bg-muted/80'
                  )}
                >
                  {t(`category_${cat}`)} ({categoryCounts[cat] || 0})
                </button>
              ))}
            </div>
            <div className='relative flex-1'>
              <Search
                size={14}
                className='absolute left-2.5 top-2.5 text-muted-foreground'
              />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('searchPlaceholder')}
                className='h-8 pl-8'
              />
            </div>
          </div>

          {!filtered.length && (
            <div className='rounded-xl border border-dashed border-border bg-muted/20 p-16 text-center'>
              <FileCode className='mx-auto mb-4 size-12 text-muted-foreground/80' />
              <p className='text-sm font-medium text-foreground'>
                {t('emptyTitle')}
              </p>
              <p className='mt-1 text-sm text-muted-foreground'>
                {t('emptyDescription')}
              </p>
              <div className='mt-6'>
                <CreateTemplateDialog />
              </div>
            </div>
          )}

          {filtered.length ? (
            <DataTable table={table} total={filtered.length} />
          ) : null}
        </>
      )}
    </div>
  );
}
