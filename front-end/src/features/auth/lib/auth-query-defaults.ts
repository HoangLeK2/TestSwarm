'use client';

import { useSearchParams } from 'next/navigation';

/** Prefill email from `?email=` (org invite accept flow). */
export function useAuthEmailFromQuery(): string {
  const searchParams = useSearchParams();
  return (searchParams.get('email') || '').trim();
}
