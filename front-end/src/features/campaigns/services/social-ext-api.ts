import { farmApi } from '@/lib/farm-api';

export type PlatformCapabilitySchema = {
  id: string;
  step_types: string[];
  input_schema_version: number;
  output_schema_version: number;
  requires_account: boolean;
  mutates_platform_state: boolean;
  safe_generic_recipes: string[];
  facets: string[];
};

export type PlatformCapabilitySupport = {
  status: string;
  execution_mode: 'generic_recipe' | 'adapter_code' | string;
  facets: Record<string, string | string[]>;
  generic_recipes: string[];
  provider_fields?: Record<string, unknown>[];
  unsupported_reason?: string;
};

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
  /** Capability support keyed by platform-neutral capability id. */
  capabilities?: Record<string, PlatformCapabilitySupport>;
  /** Capability definitions relevant to this platform. */
  capability_schemas?: Record<string, PlatformCapabilitySchema>;
};

export type NodeCatalogField = {
  name: string;
  type: string;
  label: string;
  group: string;
  required?: boolean;
  advanced?: boolean;
  description?: string;
  placeholder?: string;
  options?: unknown[];
  visible_when?: Record<string, unknown>;
  depends_on?: string[];
};

export type NodeCatalogPreset = {
  id: string;
  display_name: string;
  description: string;
  runtime_step_type: string;
  defaults: Record<string, unknown>;
};

export type NodeCatalogDefinition = {
  node_type: string;
  runtime_step_type: string;
  schema_version: number;
  display_name: string;
  description: string;
  category: string;
  capability_id?: string | null;
  fields: NodeCatalogField[];
  presets: NodeCatalogPreset[];
  legacy?: Record<string, unknown>;
};

export type SocialNodeCatalog = {
  schema_version: number;
  execution_model: 'deterministic_sequence' | string;
  nodes: NodeCatalogDefinition[];
  providers: PlatformCapability[];
};

export const socialExtApi = {
  /**
   * One request returns the whole capability matrix, so the editor never has to
   * guess which platforms a node supports.
   */
  listPlatforms: async (): Promise<PlatformCapability[]> => {
    // farmApi.baseURL already ends in /api — do not repeat the prefix here.
    const { data } = await farmApi.get<{ platforms: PlatformCapability[] }>(
      '/social-ext/platforms'
    );
    return data.platforms ?? [];
  },

  getNodeCatalog: async (): Promise<SocialNodeCatalog> => {
    const { data } = await farmApi.get<SocialNodeCatalog>(
      '/social-ext/node-catalog'
    );
    return data;
  }
};
