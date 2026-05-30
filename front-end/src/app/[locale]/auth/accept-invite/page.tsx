import { Suspense } from 'react';
import { AcceptInviteClient } from './accept-invite-client';
import { AcceptInviteLoading } from './accept-invite-loading';

export default function AcceptInvitePage() {
  return (
    <Suspense fallback={<AcceptInviteLoading />}>
      <AcceptInviteClient />
    </Suspense>
  );
}
