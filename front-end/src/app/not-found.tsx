import type { Metadata } from 'next';
import Image from 'next/image';
import { AuthLogo } from '@/features/auth';
import { ROUTES } from '@/config/routes';
import { getTranslations } from 'next-intl/server';
import './[locale]/globals.css';

export const generateMetadata = async (): Promise<Metadata> => {
  const t = await getTranslations('errors.404');
  return {
    title: t('heading'),
    description: t('description')
  };
};

export default async function GlobalNotFound() {
  const t = await getTranslations('errors.404');
  return (
    <div className='bg-not-found flex h-screen w-full items-center justify-center px-4'>
      <div className='flex w-full max-w-2xl flex-col items-center text-center'>
        {/* Logo */}
        <AuthLogo
          variant='compact'
          className='items-center'
          imageClassName='max-w-[120px]'
        />

        {/* 404 Image */}
        <Image
          src='/404.png'
          alt='404 Error'
          className='mx-auto h-auto max-w-full'
          width={600}
          height={400}
        />

        {/* Error Text */}
        <div className='absolute bottom-[20%] space-y-4'>
          <h2 className='text-xl font-semibold text-gray-800'>
            {t('heading')}
          </h2>

          <div className='mt-8'>
            <a
              href={ROUTES.DASHBOARD.ROOT}
              className='inline-flex items-center justify-center rounded-lg bg-blue-600 px-6 py-3 font-medium text-white transition-colors hover:bg-blue-700'
            >
              {t('goHome')}
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
