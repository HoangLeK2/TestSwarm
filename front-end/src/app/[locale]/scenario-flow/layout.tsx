'use client';

/**
 * Full-screen layout for the scenario flow editor — no dashboard sidebar.
 * Auth is still required; we check it via a lightweight guard.
 */
import { AuthGuard } from '@/features/auth/components/auth-guard';

export default function ScenarioFlowLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <AuthGuard>
      <div style={{ width: '100vw', height: '100vh', overflow: 'hidden' }}>
        {children}
      </div>
    </AuthGuard>
  );
}
