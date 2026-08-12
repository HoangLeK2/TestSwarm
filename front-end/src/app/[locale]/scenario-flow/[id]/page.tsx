import { redirect } from 'next/navigation';
import { ROUTES } from '@/config/routes';

export default function ScenarioFlowPage() {
  redirect(ROUTES.SCENARIO_TEMPLATES.ROOT);
}
