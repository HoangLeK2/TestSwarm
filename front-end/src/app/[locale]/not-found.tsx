'use client';

import { useRouter } from '@/i18n/navigation';
import { useTranslations } from 'next-intl';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { AuthLogo } from '@/features/auth/components/auth-logo';
import { ArrowLeft, Home } from 'lucide-react';

export default function NotFound() {
  const router = useRouter();
  const t = useTranslations('errors.404');

  return (
    <div className='flex min-h-screen items-center justify-center bg-gradient-to-br from-background via-background to-muted/20 p-4'>
      <Card className='w-full max-w-md'>
        <CardContent className='space-y-6 p-8 text-center'>
          {/* Logo */}
          <div className='flex justify-center'>
            <AuthLogo
              variant='compact'
              className='items-center'
              imageClassName='max-w-[120px]'
              textClassName='text-sm text-muted-foreground'
            />
          </div>

          {/* Error Content */}
          <div className='space-y-4'>
            <div className='space-y-2'>
              <h1 className='text-6xl font-bold text-primary'>404</h1>
              <h2 className='text-2xl font-semibold text-foreground'>
                {t('heading')}
              </h2>
            </div>

            <p className='text-sm leading-relaxed text-muted-foreground'>
              {t('description')}
            </p>

            <p className='text-xs text-muted-foreground/70'>{t('searchTip')}</p>
          </div>

          {/* Action Buttons */}
          <div className='space-y-3'>
            <Button
              onClick={() => router.push('/dashboard/product')}
              className='w-full'
            >
              <Home className='mr-2 h-4 w-4' />
              {t('goHome')}
            </Button>

            <Button
              variant='outline'
              onClick={() => router.back()}
              className='w-full'
            >
              <ArrowLeft className='mr-2 h-4 w-4' />
              {t('goBack')}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
