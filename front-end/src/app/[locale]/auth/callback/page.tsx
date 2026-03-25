import { ROUTES } from '@/config/routes';
import { redirect } from '@/i18n/navigation';

export default function OAuthCallbackPage() {
  redirect(ROUTES.DEVICES.ROOT);
}
