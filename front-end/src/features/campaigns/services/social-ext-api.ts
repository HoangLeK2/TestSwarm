import { farmApi } from '@/lib/farm-api';

/** What one platform extension can actually run, as declared by the backend. */
export type PlatformCapability = {
  name: string;
  version: string;
  /** e.g. "L2 Active" for a shipped platform, "Draft" for a stub. */
  coverage: string;
  enabled_by_default: boolean;
  /** Platform-neutral step types this platform implements. */
  step_types: string[];
  /** Entities its `extract` step can collect. */
  entities: string[];
};

export const socialExtApi = {
  /**
   * One request returns the whole capability matrix, so the editor never has to
   * guess which platforms a node supports.
   */
  listPlatforms: async (): Promise<PlatformCapability[]> => {
    const { data } = await farmApi.get<{ platforms: PlatformCapability[] }>(
      '/api/social-ext/platforms'
    );
    return data.platforms ?? [];
  }
};
