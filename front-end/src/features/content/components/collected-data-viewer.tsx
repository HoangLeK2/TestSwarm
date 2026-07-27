'use client';

import { useSearchParams } from 'next/navigation';
import { useTranslations } from 'next-intl';
import { MessageCircle, Newspaper, Users } from 'lucide-react';

import { ROUTES } from '@/config/routes';
import { useRouter } from '@/i18n/navigation';
import { cn } from '@/lib/utils';
import { GroupCatalogView } from '@/features/external-entities/components/group-catalog-view';
import { ContentViewer } from './content-viewer';

type CollectedDataTab = 'posts' | 'comments' | 'groups';

function normalizedTab(value: string | null): CollectedDataTab {
  return value === 'comments' || value === 'groups' ? value : 'posts';
}

export function CollectedDataViewer({
  defaultCampaignId,
  defaultExecutionId,
  defaultContentHash
}: {
  defaultCampaignId?: string;
  defaultExecutionId?: string;
  defaultContentHash?: string;
}) {
  const t = useTranslations('contentFeature.list');
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = defaultContentHash
    ? 'posts'
    : normalizedTab(searchParams.get('tab'));
  const tabs = [
    { value: 'posts', label: t('tabPosts'), icon: Newspaper },
    { value: 'comments', label: t('tabComments'), icon: MessageCircle },
    { value: 'groups', label: t('tabGroups'), icon: Users }
  ] as const;

  const changeTab = (tab: CollectedDataTab) => {
    const params = new URLSearchParams(searchParams.toString());
    if (tab !== 'posts') params.delete('content_hash');
    if (tab === 'posts') params.delete('tab');
    else params.set('tab', tab);
    const query = params.toString();
    router.replace(
      query ? `${ROUTES.CONTENT.ROOT}?${query}` : ROUTES.CONTENT.ROOT,
      {
        scroll: false
      }
    );
  };

  return (
    <div className='space-y-4'>
      <div className='inline-flex items-center gap-1 rounded-xl bg-muted/60 p-1 ring-1 ring-border/40'>
        {tabs.map((tab) => {
          const Icon = tab.icon;
          const active = activeTab === tab.value;
          return (
            <button
              key={tab.value}
              type='button'
              onClick={() => changeTab(tab.value)}
              className={cn(
                'inline-flex cursor-pointer items-center gap-1.5 rounded-lg px-3 py-2 text-sm font-medium transition-all',
                active
                  ? 'bg-background text-foreground shadow-sm ring-1 ring-border/60'
                  : 'text-muted-foreground hover:bg-background/60 hover:text-foreground'
              )}
              aria-pressed={active}
            >
              <Icon className='size-4' />
              {tab.label}
            </button>
          );
        })}
      </div>

      {activeTab === 'groups' ? (
        <GroupCatalogView />
      ) : (
        <ContentViewer
          key={activeTab}
          defaultCampaignId={defaultCampaignId}
          defaultExecutionId={defaultExecutionId}
          defaultContentHash={defaultContentHash}
          defaultContentType={
            activeTab === 'comments' ? 'fb_comment' : 'fb_post'
          }
          showContentTypeTabs={false}
        />
      )}
    </div>
  );
}
