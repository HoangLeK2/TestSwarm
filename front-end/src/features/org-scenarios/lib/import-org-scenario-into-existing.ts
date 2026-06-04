import { orgScenariosApi } from '../services/api';
import type { OrgScenarioImportOut } from '../services/api';

/** Import portable file content directly onto an existing scenario (no duplicate-name create). */
export async function importOrgScenarioFileIntoExisting(
  file: File,
  targetScenarioId: string,
  resolve: 'reject' | 'create_stub' = 'reject'
): Promise<OrgScenarioImportOut> {
  return orgScenariosApi.importFileIntoExisting(
    targetScenarioId,
    file,
    resolve
  );
}
