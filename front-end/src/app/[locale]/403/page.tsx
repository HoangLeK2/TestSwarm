'use client';

import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { AuthLogo } from '@/features/auth/components/auth-logo';
import { Link } from '@/i18n/navigation';
import { ROUTES } from '@/config/routes';
import { Home } from 'lucide-react';
import { getTranslations } from 'next-intl/server';

export default async function ForbiddenPage() {
  const t = await getTranslations('errors.403');

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
              <h1 className='text-6xl font-bold text-destructive'>403</h1>
              <h2 className='text-2xl font-semibold text-foreground'>
                {t('heading')}
              </h2>
            </div>

            <p className='text-sm leading-relaxed text-muted-foreground'>
              {t('description')}
            </p>
          </div>

          {/* Action Buttons */}
          <div className='space-y-3'>
            <Button asChild className='w-full' variant='outline'>
              <Link href={ROUTES.DASHBOARD.ROOT}>
                <Home className='mr-2 h-4 w-4' />
                {t('goHome')}
              </Link>
            </Button>

            {/* <Button variant="outline" asChild className="flex-1">
                <Link href="mailto:admin@ndatrace.com">
                  <Mail className="mr-2 h-4 w-4" />
                  {t('contactAdmin')}
                </Link>
              </Button> */}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
