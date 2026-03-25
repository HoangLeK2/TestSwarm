import { ROUTES } from '@/config/routes';
import { redirect } from '@/i18n/navigation';

export default function VerifyEmailPage() {
  redirect(ROUTES.DEVICES.ROOT);
}
