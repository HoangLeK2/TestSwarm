import { DashboardWrapper } from '@/components/layout/dashboard-wrapper';
import { AuthGuard } from '@/features/auth/components/auth-guard';
// import { cookies } from 'next/headers';

export default async function DashboardLayout({
  children
}: {
  children: React.ReactNode;
}) {
  // const cookieStore = await cookies();
  // const defaultOpen = cookieStore.get('sidebar_state')?.value === 'true';

  return (
    <AuthGuard>
      <DashboardWrapper defaultOpen={true}>{children}</DashboardWrapper>
    </AuthGuard>
  );
}
