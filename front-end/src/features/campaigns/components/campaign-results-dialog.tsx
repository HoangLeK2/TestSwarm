'use client';

/**
 * CampaignResultsDialog — Hiển thị thống kê + dữ liệu đã cào cho 1 chiến dịch.
 * Mở từ CampaignRowActions khi chiến dịch đã/đang chạy.
 */

import { useEffect, useState } from 'react';
import {
  BarChart3,
  Database,
  FileText,
  MessageSquare,
  RefreshCw
} from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger
} from '@/components/ui/tooltip';
import { ContentViewer } from '@/features/content/components/content-viewer';
import { contentApi } from '@/features/content/services/api';
import type { CampaignOut } from '../types';

// ── Quick stats ───────────────────────────────────────────────────────────────

interface QuickStats {
  posts: number;
  comments: number;
  total: number;
}

function useQuickStats(campaignId: string, enabled: boolean) {
  const [stats, setStats] = useState<QuickStats | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled || !campaignId) return;
    setLoading(true);

    Promise.all([
      contentApi.list({
        campaign_id: campaignId,
        content_type: 'group_post',
        limit: 1
      }),
      contentApi.list({
        campaign_id: campaignId,
        content_type: 'group_comment',
        limit: 1
      }),
      contentApi.list({ campaign_id: campaignId, limit: 1 })
    ])
      .then(([posts, comments, all]) => {
        setStats({
          posts: posts.total,
          comments: comments.total,
          total: all.total
        });
      })
      .catch(() => setStats(null))
      .finally(() => setLoading(false));
  }, [campaignId, enabled]);

  return { stats, loading };
}

function StatCard({
  icon,
  label,
  value,
  loading
}: {
  icon: React.ReactNode;
  label: string;
  value: number | null;
  loading: boolean;
}) {
  return (
    <div className='flex items-center gap-3 rounded-lg border bg-card px-3 py-2.5'>
      <div className='shrink-0'>{icon}</div>
      <div className='min-w-0'>
        <p className='truncate text-[10px] text-muted-foreground'>{label}</p>
        <p className='truncate text-sm font-bold text-foreground'>
          {loading ? (
            <RefreshCw className='size-3 animate-spin text-muted-foreground' />
          ) : (
            (value ?? 0).toLocaleString('vi-VN')
          )}
        </p>
      </div>
    </div>
  );
}

// ── Main dialog ───────────────────────────────────────────────────────────────

interface Props {
  campaign: CampaignOut;
  children?: React.ReactNode;
}

export function CampaignResultsDialog({ campaign, children }: Props) {
  const [open, setOpen] = useState(false);
  const { stats, loading } = useQuickStats(campaign.id, open);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <Tooltip>
        <TooltipTrigger asChild>
          <DialogTrigger asChild>
            {children ?? (
              <Button
                size='sm'
                variant='ghost'
                className='h-7 gap-1.5 px-2 text-xs'
              >
                <BarChart3 size={13} />
              </Button>
            )}
          </DialogTrigger>
        </TooltipTrigger>
        <TooltipContent side='top' className='text-xs'>
          Kết quả thu thập
        </TooltipContent>
      </Tooltip>

      <DialogContent className='max-w-5xl gap-0 p-0'>
        <DialogHeader className='border-b px-5 py-3'>
          <div className='flex items-center gap-2'>
            <BarChart3 size={15} className='text-primary' />
            <DialogTitle className='text-sm font-semibold'>
              Kết quả — {campaign.name}
            </DialogTitle>
          </div>
          <p className='mt-0.5 font-mono text-[10px] text-muted-foreground'>
            {campaign.id}
          </p>
        </DialogHeader>

        <div className='max-h-[82vh] overflow-y-auto'>
          {/* Quick stats */}
          <div className='border-b px-5 py-4'>
            <div className='grid grid-cols-3 gap-3'>
              <StatCard
                icon={<Database className='size-4 text-primary' />}
                label='Tổng bản ghi'
                value={stats?.total ?? null}
                loading={loading}
              />
              <StatCard
                icon={<FileText className='size-4 text-emerald-500' />}
                label='Bài viết'
                value={stats?.posts ?? null}
                loading={loading}
              />
              <StatCard
                icon={<MessageSquare className='size-4 text-blue-500' />}
                label='Bình luận'
                value={stats?.comments ?? null}
                loading={loading}
              />
            </div>
          </div>

          {/* Full content viewer filtered by campaign */}
          <div className='p-5'>
            <ContentViewer defaultCampaignId={campaign.id} />
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
