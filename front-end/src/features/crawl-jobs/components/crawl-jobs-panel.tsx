'use client';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Switch } from '@/components/ui/switch';
import { useCampaigns } from '@/features/campaigns/hooks/use-campaigns';
import { scenariosApi } from '@/features/campaigns/services/api';
import type { ScenarioOut } from '@/features/campaigns/types';
import { useDevices } from '@/features/devices/hooks/use-devices';
import { useTranslations } from 'next-intl';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { CrawlJob, CrawlPost, crawlJobsApi } from '../services/api';

function statusVariant(status: string): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'done') return 'default';
  if (status === 'failed') return 'destructive';
  if (status === 'running') return 'secondary';
  return 'outline';
}

function hasFbExtractInSteps(steps: unknown): boolean {
  if (!Array.isArray(steps)) return false;
  for (const step of steps) {
    if (!step || typeof step !== 'object') continue;
    const s = step as Record<string, any>;
    if (s.type === 'extract' && s.strategy === 'fb_posts') return true;
    if (hasFbExtractInSteps(s.steps)) return true;
  }
  return false;
}

export function CrawlJobsPanel({ campaignId }: { campaignId?: string }) {
  const t = useTranslations('crawlJobs');
  const { data: campaigns } = useCampaigns();
  const { data: devices } = useDevices();
  const [jobs, setJobs] = useState<CrawlJob[]>([]);
  const [loadingJobs, setLoadingJobs] = useState(false);
  const [jobsError, setJobsError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [selectedCampaignId, setSelectedCampaignId] = useState<string>(campaignId ?? '');
  const [scenarios, setScenarios] = useState<ScenarioOut[]>([]);
  const [selectedScenarioId, setSelectedScenarioId] = useState('');
  const [selectedSerial, setSelectedSerial] = useState('');
  const [groupId, setGroupId] = useState('');
  const [autoAppendCrawl, setAutoAppendCrawl] = useState(true);

  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [posts, setPosts] = useState<CrawlPost[]>([]);
  const [loadingPosts, setLoadingPosts] = useState(false);
  const [postsError, setPostsError] = useState<string | null>(null);

  const selectedJob = useMemo(
    () => jobs.find((job) => job.id === selectedJobId) ?? null,
    [jobs, selectedJobId]
  );
  const selectedScenario = useMemo(
    () => scenarios.find((s) => s.id === selectedScenarioId) ?? null,
    [scenarios, selectedScenarioId]
  );
  const selectedScenarioHasExtract = useMemo(
    () => hasFbExtractInSteps(selectedScenario?.steps),
    [selectedScenario]
  );

  const loadJobs = useCallback(async () => {
    setLoadingJobs(true);
    setJobsError(null);
    try {
      const data = await crawlJobsApi.list({ campaignId });
      setJobs(data);
      if (!selectedJobId && data.length > 0) setSelectedJobId(data[0].id);
      if (selectedJobId && !data.some((job) => job.id === selectedJobId)) {
        setSelectedJobId(data[0]?.id ?? null);
      }
    } catch (err: any) {
      setJobsError(err?.response?.data?.error ?? err?.message ?? t('loadJobsFailed'));
    } finally {
      setLoadingJobs(false);
    }
  }, [campaignId, selectedJobId, t]);

  const createJob = useCallback(async () => {
    if (!selectedSerial) {
      setCreateError(t('serialRequired'));
      return;
    }
    if (!selectedCampaignId && !selectedScenarioId) {
      setCreateError(t('campaignOrScenarioRequired'));
      return;
    }
    setCreating(true);
    setCreateError(null);
    try {
      await crawlJobsApi.enqueue(selectedSerial, {
        campaign_id: selectedCampaignId || undefined,
        scenario_id: selectedScenarioId || undefined,
        group_id: groupId.trim(),
        app: 'chrome',
        expand_posts: true,
        auto_append_crawl: autoAppendCrawl,
        name: selectedCampaignId
          ? `Campaign ${selectedCampaignId}${groupId.trim() ? ` - Group ${groupId.trim()}` : ''}`
          : selectedScenarioId
            ? `Scenario ${selectedScenarioId}${groupId.trim() ? ` - Group ${groupId.trim()}` : ''}`
            : `Crawl Job${groupId.trim() ? ` - Group ${groupId.trim()}` : ''}`
      });
      await loadJobs();
    } catch (err: any) {
      setCreateError(err?.response?.data?.error ?? err?.message ?? t('createFailed'));
    } finally {
      setCreating(false);
    }
  }, [
    groupId,
    loadJobs,
    selectedCampaignId,
    selectedScenarioId,
    selectedSerial,
    autoAppendCrawl,
    t
  ]);

  const loadPosts = useCallback(
    async (jobId: string) => {
      setLoadingPosts(true);
      setPostsError(null);
      try {
        const data = await crawlJobsApi.getPosts(jobId);
        setPosts(data);
      } catch (err: any) {
        setPostsError(err?.response?.data?.error ?? err?.message ?? t('loadPostsFailed'));
      } finally {
        setLoadingPosts(false);
      }
    },
    [t]
  );

  useEffect(() => {
    void loadJobs();
  }, [loadJobs]);

  useEffect(() => {
    if (!selectedJobId) {
      setPosts([]);
      return;
    }
    void loadPosts(selectedJobId);
  }, [selectedJobId, loadPosts]);

  useEffect(() => {
    if (!selectedCampaignId) {
      setScenarios([]);
      setSelectedScenarioId('');
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const list = await scenariosApi.list(selectedCampaignId);
        if (!cancelled) {
          setScenarios(list);
          setSelectedScenarioId((current) => (current && list.some((s) => s.id === current) ? current : ''));
        }
      } catch {
        if (!cancelled) setScenarios([]);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedCampaignId]);

  return (
    <div className='space-y-4'>
      <Card>
        <CardHeader>
          <CardTitle>{t('createTitle')}</CardTitle>
        </CardHeader>
        <CardContent className='grid gap-3 md:grid-cols-2'>
          <div className='space-y-1'>
            <p className='text-xs text-muted-foreground'>{t('campaign')}</p>
            <select
              className='flex h-9 w-full rounded border border-input bg-transparent px-3 py-1 text-sm'
              value={selectedCampaignId}
              onChange={(e) => setSelectedCampaignId(e.target.value)}
            >
              <option value=''>{t('campaignOptional')}</option>
              {(campaigns ?? []).map((campaign) => (
                <option key={campaign.id} value={campaign.id}>
                  {campaign.name}
                </option>
              ))}
            </select>
          </div>
          <div className='space-y-1'>
            <p className='text-xs text-muted-foreground'>{t('device')}</p>
            <select
              className='flex h-9 w-full rounded border border-input bg-transparent px-3 py-1 text-sm'
              value={selectedSerial}
              onChange={(e) => setSelectedSerial(e.target.value)}
            >
              <option value=''>{t('selectDevice')}</option>
              {(devices ?? []).map((device) => (
                <option key={device.id} value={device.serial}>
                  {device.name || device.serial} ({device.serial})
                </option>
              ))}
            </select>
          </div>
          <div className='space-y-1'>
            <p className='text-xs text-muted-foreground'>Group ID (optional)</p>
            <Input
              value={groupId}
              onChange={(e) => setGroupId(e.target.value)}
              placeholder='123456789'
            />
          </div>
          <div className='space-y-1'>
            <p className='text-xs text-muted-foreground'>{t('scenarioOptional')}</p>
            <select
              className='flex h-9 w-full rounded border border-input bg-transparent px-3 py-1 text-sm'
              value={selectedScenarioId}
              onChange={(e) => setSelectedScenarioId(e.target.value)}
              disabled={!selectedCampaignId}
            >
              <option value=''>{t('allScenariosInCampaign')}</option>
              {scenarios.map((scenario) => (
                <option key={scenario.id} value={scenario.id}>
                  {scenario.name}
                </option>
              ))}
            </select>
            {selectedScenarioId && !selectedScenarioHasExtract ? (
              <p className='text-xs text-amber-600'>{t('scenarioNoExtractWarning')}</p>
            ) : null}
          </div>
          <div className='space-y-2'>
            <p className='text-xs text-muted-foreground'>{t('autoAppendCrawl')}</p>
            <div className='flex items-center gap-2'>
              <Switch checked={autoAppendCrawl} onCheckedChange={setAutoAppendCrawl} />
              <span className='text-xs text-muted-foreground'>
                {autoAppendCrawl ? t('autoAppendOn') : t('autoAppendOff')}
              </span>
            </div>
          </div>
          <div className='flex items-end'>
            <Button onClick={() => void createJob()} disabled={creating}>
              {creating ? t('creating') : t('runNow')}
            </Button>
          </div>
          {createError ? <p className='text-sm text-destructive md:col-span-2'>{createError}</p> : null}
        </CardContent>
      </Card>

      <div className='grid gap-4 lg:grid-cols-2'>
      <Card>
        <CardHeader className='flex flex-row items-center justify-between space-y-0'>
          <CardTitle>{t('jobsTitle')}</CardTitle>
          <Button size='sm' variant='outline' onClick={() => void loadJobs()} disabled={loadingJobs}>
            {t('refresh')}
          </Button>
        </CardHeader>
        <CardContent className='space-y-2'>
          {jobsError ? <p className='text-sm text-destructive'>{jobsError}</p> : null}
          {loadingJobs ? <p className='text-sm text-muted-foreground'>{t('loading')}</p> : null}
          {!loadingJobs && jobs.length === 0 ? (
            <p className='text-sm text-muted-foreground'>{t('emptyJobs')}</p>
          ) : null}

          {jobs.map((job) => (
            <button
              key={job.id}
              type='button'
              className={`w-full rounded-md border p-3 text-left ${
                selectedJobId === job.id ? 'border-primary bg-primary/5' : 'border-border'
              }`}
              onClick={() => setSelectedJobId(job.id)}
            >
              <div className='flex items-center justify-between gap-2'>
                <p className='truncate text-sm font-medium'>{job.name || job.group_id}</p>
                <Badge variant={statusVariant(job.status)}>{job.status}</Badge>
              </div>
              <p className='mt-1 text-xs text-muted-foreground'>
                {t('device')}: {job.device_serial} | {t('posts')}: {job.total_posts}
              </p>
              {job.campaign_id ? (
                <p className='mt-1 text-xs text-muted-foreground'>
                  {t('campaign')}: {job.campaign_id}
                </p>
              ) : null}
            </button>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className='flex flex-row items-center justify-between space-y-0'>
          <CardTitle>{t('postsTitle')}</CardTitle>
          {selectedJob ? (
            <Button
              size='sm'
              variant='outline'
              onClick={() => void loadPosts(selectedJob.id)}
              disabled={loadingPosts}
            >
              {t('refresh')}
            </Button>
          ) : null}
        </CardHeader>
        <CardContent className='space-y-2'>
          {!selectedJob ? <p className='text-sm text-muted-foreground'>{t('selectJob')}</p> : null}
          {postsError ? <p className='text-sm text-destructive'>{postsError}</p> : null}
          {loadingPosts ? <p className='text-sm text-muted-foreground'>{t('loading')}</p> : null}
          {!loadingPosts && selectedJob && posts.length === 0 ? (
            <p className='text-sm text-muted-foreground'>{t('emptyPosts')}</p>
          ) : null}

          {posts.map((post) => (
            <div key={post.id} className='rounded-md border p-3'>
              <div className='flex items-center justify-between gap-2'>
                <p className='truncate text-sm font-semibold'>{post.author || t('unknownAuthor')}</p>
                <span className='text-xs text-muted-foreground'>#{post.source_index}</span>
              </div>
              <p className='mt-1 whitespace-pre-wrap text-sm'>{post.text || '...'}</p>
              <p className='mt-1 text-xs text-muted-foreground'>
                {post.timestamp_raw || '-'} | {t('reactions')}: {post.reactions || '0'} |{' '}
                {t('comments')}: {post.comments || '0'} | {t('shares')}: {post.shares || '0'}
              </p>
            </div>
          ))}
        </CardContent>
      </Card>
      </div>
    </div>
  );
}
