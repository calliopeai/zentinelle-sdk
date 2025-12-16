/**
 * Type definitions for Zentinelle SDK.
 */

export type PolicyType =
  | 'rate_limit'
  | 'cost_limit'
  | 'pii_filter'
  | 'prompt_injection'
  | 'system_prompt'
  | 'model_restriction'
  | 'human_oversight'
  | 'agent_capability'
  | 'agent_memory'
  | 'data_retention'
  | 'audit_log';

export type Enforcement = 'enforce' | 'warn' | 'log' | 'disabled';

export type EventCategory = 'telemetry' | 'audit' | 'alert' | 'compliance';

export interface PolicyConfig {
  id: string;
  name: string;
  type: PolicyType;
  enforcement: Enforcement;
  config: Record<string, unknown>;
  priority?: number;
}

export interface EvaluateResult {
  allowed: boolean;
  reason?: string;
  policiesEvaluated: Array<{
    name: string;
    type: string;
    passed: boolean;
    message?: string;
  }>;
  warnings: string[];
  context: Record<string, unknown>;
  /** Indicates if this result was returned due to fail-open mode (service unavailable) */
  failOpen?: boolean;
}

export interface RegisterResult {
  agentId: string;
  apiKey?: string;
  config: Record<string, unknown>;
  policies: PolicyConfig[];
}

export interface ConfigResult {
  agentId: string;
  config: Record<string, unknown>;
  policies: PolicyConfig[];
  updatedAt: Date;
}

export interface SecretsResult {
  secrets: Record<string, string>;
  providers: Record<string, unknown>;
  expiresAt: Date;
}

export interface EventsResult {
  accepted: number;
  batchId: string;
}

export interface HeartbeatResult {
  acknowledged: boolean;
  configChanged: boolean;
  nextHeartbeatSeconds: number;
}

export interface ModelUsage {
  provider: string;
  model: string;
  inputTokens: number;
  outputTokens: number;
  estimatedCost?: number;
}

export interface Event {
  type: string;
  category: EventCategory;
  payload: Record<string, unknown>;
  timestamp: string;
  userId?: string;
}
