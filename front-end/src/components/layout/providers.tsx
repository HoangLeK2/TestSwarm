'use client';
import React from 'react';
import { ActiveThemeProvider } from '../active-theme';
import { AuthProvider } from '@/features/auth/providers/auth-provider';
import { PermissionProvider } from '@/features/auth/providers/permission-provider';
import { QueryProvider } from '@/providers/query-provider';
import { NuqsAdapter } from 'nuqs/adapters/next/app';
import { Toaster } from '../ui/sonner';
import { ModalProvider } from '@/providers/modal-provider';
import { OrganizationProvider } from '@/features/organization/providers/organization-provider';

export default function Providers({
  activeThemeValue,
  children
}: {
  activeThemeValue: string;
  children: React.ReactNode;
}) {
  return (
    <QueryProvider>
      <ModalProvider>
        <ActiveThemeProvider initialTheme={activeThemeValue}>
          <AuthProvider>
            <PermissionProvider>
              <NuqsAdapter>
                <OrganizationProvider>
                  <Toaster duration={3000} position='top-right' />
                  {children}
                </OrganizationProvider>
              </NuqsAdapter>
            </PermissionProvider>
          </AuthProvider>
        </ActiveThemeProvider>
      </ModalProvider>
    </QueryProvider>
  );
}
