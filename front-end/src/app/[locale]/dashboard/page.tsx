import { ROUTES } from '@/config/routes';
import { redirect } from '@/i18n/navigation';

export default function Page() {
  redirect(ROUTES.DEVICES.ROOT);
}
