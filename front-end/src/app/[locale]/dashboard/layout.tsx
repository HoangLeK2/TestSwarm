import { DashboardWrapper } from '@/components/layout/dashboard-wrapper';
import { AuthGuard } from '@/features/auth/components/auth-guard';
import { PermissionGuard } from '@/features/auth/components/permission-guard';

export default async function DashboardLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthGuard>
      <PermissionGuard>
        <DashboardWrapper defaultOpen={true}>{children}</DashboardWrapper>
      </PermissionGuard>
    </AuthGuard>
  );
}
