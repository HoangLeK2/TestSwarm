'use client';

import AppSidebar from '@/components/layout/app-sidebar';
import Header from '@/components/layout/header';
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar';
import { ReactNode } from 'react';
import PageContainer from './page-container';
// import { AuthGuard } from '@/features/auth';
// import { OrganizationProvider } from '@/features/organization/providers/organization-provider';
// import { OrganizationStatusGuard } from '@/features/organization/components/organization-status-guard';

interface DashboardWrapperProps {
  children: ReactNode;
  defaultOpen?: boolean;
}

export function DashboardWrapper({
  children,
  defaultOpen = true
}: DashboardWrapperProps) {
  return (
    // <AuthGuard>
    // <OrganizationProvider>
    // <OrganizationStatusGuard>
    <SidebarProvider
      defaultOpen={defaultOpen}
      className='h-svh min-h-0 overflow-hidden'
    >
      <AppSidebar />
      <SidebarInset className='flex min-h-0 flex-1 flex-col overflow-hidden'>
        <Header />
        <PageContainer
          className='h-[calc(100dvh-64px)] overflow-scroll'
          scrollable={false}
        >
          {children}
        </PageContainer>
      </SidebarInset>
    </SidebarProvider>
    // </OrganizationStatusGuard>
    // </OrganizationProvider>
    // </AuthGuard>
  );
}
