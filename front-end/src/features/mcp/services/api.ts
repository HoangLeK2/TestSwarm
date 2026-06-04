import { farmApi } from '@/lib/farm-api';

export type McpToolDescriptor = {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  outputSchema: Record<string, unknown>;
  metadata: {
    route: string;
    token_scope: 'device' | 'user' | 'any' | string;
    stability: string;
    preview: boolean;
    contract_version: string;
  };
};

export type McpTokenRecord = {
  id: string;
  name: string;
  prefix: string;
  scope_type: string;
  scope_ref?: string | null;
  status: string;
  created_at?: number;
  revoked_at?: number | null;
  source?: string;
};

export type McpAuditEntry = {
  session_id?: string | null;
  agent_id?: string | null;
  token_id_hash?: string | null;
  tool_name: string;
  result_code: string;
  started_at: number;
  ended_at: number;
  latency_ms: number;
  input?: Record<string, unknown>;
  output_summary?: Record<string, unknown>;
};

export async function getMcpTools() {
  const { data } = await farmApi.get<{
    preview: boolean;
    contract_version: string;
    warning: string;
    tools: McpToolDescriptor[];
    error_catalog: Record<string, { retryable: boolean; http_status: number }>;
  }>('/mcp/tools');
  return data;
}

export async function getMcpTokens() {
  const { data } = await farmApi.get<{
    preview: boolean;
    contract_version: string;
    tokens: McpTokenRecord[];
  }>('/mcp/tokens');
  return data;
}

export async function createMcpToken(input: {
  name: string;
  scope_type: 'device' | 'user';
  scope_ref?: string;
  preview_consent: boolean;
}) {
  const { data } = await farmApi.post<{
    token: string;
    record: McpTokenRecord;
    warning: string;
  }>('/mcp/tokens', input);
  return data;
}

export async function revokeMcpToken(tokenId: string) {
  const { data } = await farmApi.post<{ ok: boolean }>(
    `/mcp/tokens/${encodeURIComponent(tokenId)}/revoke`
  );
  return data;
}

export async function getMcpAuditLog() {
  const { data } = await farmApi.get<{
    preview: boolean;
    contract_version: string;
    total: number;
    entries: McpAuditEntry[];
  }>('/mcp/audit-log?limit=100');
  return data;
}
