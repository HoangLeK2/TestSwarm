'use client';

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { ExternalLink, Heart, MessageCircle, Share2, Eye } from 'lucide-react';
import type { ContentItem } from '../services/api';

interface Props {
  item: ContentItem | null;
  onClose: () => void;
  onViewParent?: (parentId: string) => void;
}

/** tags có thể là JSON array '["a","b"]' hoặc CSV "a,b,c" */
function parseTags(raw: string): string[] {
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.map(String).filter(Boolean);
  } catch {
    // not JSON — treat as comma-separated
  }
  return raw.split(',').map((s) => s.trim()).filter(Boolean);
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className='grid grid-cols-[120px_1fr] gap-2 py-1.5 border-b border-border/30 last:border-0'>
      <span className='text-[11px] font-medium text-muted-foreground'>{label}</span>
      <div className='min-w-0 text-xs text-foreground'>{children}</div>
    </div>
  );
}

export function ContentDetailDialog({ item, onClose, onViewParent }: Props) {
  if (!item) return null;

  const time = item.extracted_at
    ? new Date(item.extracted_at).toLocaleString('vi-VN')
    : '–';

  return (
    <Dialog open={!!item} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className='max-w-lg max-h-[85vh] overflow-y-auto'>
        <DialogHeader>
          <DialogTitle className='flex items-center gap-2 text-sm'>
            Chi tiết dữ liệu
            {item.platform && <Badge variant='secondary'>{item.platform}</Badge>}
            <Badge variant='outline'>{item.content_type}</Badge>
          </DialogTitle>
        </DialogHeader>

        <div className='space-y-0.5'>
          {(item as any).item_level > 0 && (item as any).parent_id && (
            <Row label='Bài gốc'>
              <button
                type='button'
                onClick={() => { onViewParent?.((item as any).parent_id); onClose(); }}
                className='flex items-center gap-1 text-blue-600 hover:underline dark:text-blue-400'
              >
                <ExternalLink size={10} />
                Xem bài đăng gốc
              </button>
            </Row>
          )}
          <Row label='Collection'>{item.collection}</Row>
          <Row label='Thời gian cào'>{time}</Row>
          {item.device_serial && <Row label='Thiết bị'><span className='font-mono'>{item.device_serial}</span></Row>}
          {item.scenario_name && <Row label='Kịch bản'>{item.scenario_name}</Row>}

          {item.title && (
            <Row label='Tiêu đề'>
              <p className='font-medium'>{item.title}</p>
            </Row>
          )}

          {item.body && (
            <Row label='Nội dung'>
              <p className='whitespace-pre-wrap leading-relaxed text-foreground/80'>{item.body}</p>
            </Row>
          )}

          {item.author && <Row label='Tác giả'>{item.author}{item.author_id && <span className='ml-1 text-muted-foreground'>({item.author_id})</span>}</Row>}

          {item.url && (
            <Row label='URL'>
              <a href={item.url} target='_blank' rel='noopener noreferrer'
                className='flex items-center gap-1 text-primary hover:underline break-all'>
                <ExternalLink size={11} className='shrink-0' />
                {item.url}
              </a>
            </Row>
          )}

          {(item.likes_count != null || item.comments_count != null || item.shares_count != null || item.views_count != null) && (
            <Row label='Tương tác'>
              <div className='flex flex-wrap gap-3'>
                {item.likes_count != null && (
                  <span className='flex items-center gap-1'><Heart size={11} className='text-red-400' />{item.likes_count.toLocaleString()}</span>
                )}
                {item.comments_count != null && (
                  <span className='flex items-center gap-1'><MessageCircle size={11} className='text-blue-400' />{item.comments_count.toLocaleString()}</span>
                )}
                {item.shares_count != null && (
                  <span className='flex items-center gap-1'><Share2 size={11} className='text-green-400' />{item.shares_count.toLocaleString()}</span>
                )}
                {item.views_count != null && (
                  <span className='flex items-center gap-1'><Eye size={11} className='text-violet-400' />{item.views_count.toLocaleString()}</span>
                )}
              </div>
            </Row>
          )}

          {item.media_urls?.length > 0 && (
            <Row label='Media'>
              <div className='space-y-0.5'>
                {item.media_urls.map((url, i) => (
                  <a key={i} href={url} target='_blank' rel='noopener noreferrer'
                    className='flex items-center gap-1 text-primary hover:underline break-all text-[11px]'>
                    <ExternalLink size={9} className='shrink-0' />
                    {url}
                  </a>
                ))}
              </div>
            </Row>
          )}

          {item.tags && item.tags !== '[]' && item.tags !== '' && (
            <Row label='Tags'>
              <div className='flex flex-wrap gap-1'>
                {parseTags(item.tags).map((tag: string, i: number) => (
                  <Badge key={i} variant='secondary' className='text-[9px]'>{tag}</Badge>
                ))}
              </div>
            </Row>
          )}

          {item.raw_data && (
            <Row label='Dữ liệu gốc'>
              <pre className='max-h-48 overflow-y-auto rounded bg-muted px-2 py-1.5 text-[10px] leading-relaxed'>
                {JSON.stringify(item.raw_data, null, 2)}
              </pre>
            </Row>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
