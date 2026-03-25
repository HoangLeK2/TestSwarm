'use client';

import { env } from '@/constants/env';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { useState } from 'react';

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 1000 * 60 * 5, // 5 minutes
            gcTime: 1000 * 60 * 10, // 10 minutes
            retry: (failureCount, error: any) => {
              if (error?.status === 404 || error?.status === 401) {
                return false;
              }
              return failureCount < 2;
            },
            refetchOnWindowFocus: true
          },
          mutations: {
            retry: 1
          }
        }
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      {children}
      {env.ENVIRONMENT === 'dev' && (
        <ReactQueryDevtools initialIsOpen={false} position='bottom' />
      )}
    </QueryClientProvider>
  );
}
