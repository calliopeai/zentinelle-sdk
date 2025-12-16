/**
 * Zentinelle SDK - AI Agent Governance & Runtime Control
 *
 * @example
 * ```typescript
 * import { ZentinelleClient } from 'zentinelle';
 *
 * const client = new ZentinelleClient({
 *   apiKey: 'sk_agent_...',
 *   agentType: 'vercel-ai',
 * });
 *
 * // Register on startup
 * await client.register({ capabilities: ['chat', 'tools'] });
 *
 * // Evaluate policies
 * const result = await client.evaluate('tool_call', { userId: 'user123' });
 *
 * // Track usage
 * client.trackUsage({ provider: 'openai', model: 'gpt-4o', inputTokens: 100, outputTokens: 50 });
 * ```
 */

export const VERSION = '0.1.0';

export { ZentinelleClient } from './client';
export type { ZentinelleClientOptions } from './client';

export {
  ZentinelleError,
  ZentinelleConnectionError,
  ZentinelleAuthError,
  ZentinelleRateLimitError,
  PolicyViolationError,
} from './errors';

export type {
  EvaluateResult,
  PolicyConfig,
  RegisterResult,
  ConfigResult,
  ModelUsage,
  EventCategory,
  PolicyType,
  Enforcement,
} from './types';

export { RetryConfig, CircuitBreaker } from './resilience';
