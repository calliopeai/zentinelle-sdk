/**
 * Zentinelle SDK Client - Main client for AI agent governance.
 */

import {
  ZentinelleError,
  ZentinelleConnectionError,
  ZentinelleAuthError,
  ZentinelleRateLimitError,
} from './errors';
import { RetryConfig, CircuitBreaker } from './resilience';
import type {
  EvaluateResult,
  PolicyConfig,
  RegisterResult,
  ConfigResult,
  ModelUsage,
  EventCategory,
  Event,
  EventsResult,
  HeartbeatResult,
} from './types';

export interface ZentinelleClientOptions {
  apiKey: string;
  agentType: string;
  endpoint?: string;
  agentId?: string;
  orgId?: string;
  timeout?: number;
  retryConfig?: RetryConfig;
  circuitBreakerThreshold?: number;
  circuitBreakerRecovery?: number;
  failOpen?: boolean;
  autoFlush?: boolean;
  flushInterval?: number;
  bufferSize?: number;
}

export class ZentinelleClient {
  private readonly endpoint: string;
  private readonly apiKey: string;
  private readonly agentType: string;
  private agentId: string | null;
  private readonly orgId?: string;
  private readonly timeout: number;
  private readonly failOpen: boolean;

  private readonly retryConfig: RetryConfig;
  private readonly circuitBreaker: CircuitBreaker;

  private eventBuffer: Event[] = [];
  private readonly bufferSize: number;
  private flushTimer: ReturnType<typeof setInterval> | null = null;

  private configCache: Record<string, unknown> | null = null;
  private configCacheTime: Date | null = null;
  private readonly configCacheTtl = 300000; // 5 minutes

  private secretsCache: Record<string, string> | null = null;
  private secretsCacheTime: Date | null = null;
  private readonly secretsCacheTtl = 60000; // 1 minute

  private registered = false;

  constructor(options: ZentinelleClientOptions) {
    this.endpoint = (options.endpoint ?? 'https://api.zentinelle.ai').replace(/\/$/, '');
    this.apiKey = options.apiKey;
    this.agentType = options.agentType;
    this.agentId = options.agentId ?? null;
    this.orgId = options.orgId;
    this.timeout = options.timeout ?? 30000;
    this.failOpen = options.failOpen ?? false;
    this.bufferSize = options.bufferSize ?? 100;

    this.retryConfig = options.retryConfig ?? new RetryConfig();
    this.circuitBreaker = new CircuitBreaker({
      failureThreshold: options.circuitBreakerThreshold ?? 5,
      recoveryTimeout: options.circuitBreakerRecovery ?? 30000,
    });

    // Start auto-flush if enabled
    if (options.autoFlush !== false) {
      const interval = options.flushInterval ?? 5000;
      this.flushTimer = setInterval(() => {
        if (this.registered) {
          this.flushEvents().catch(() => {});
        }
      }, interval);
    }
  }

  // ===========================================================================
  // HTTP Helpers
  // ===========================================================================

  private getHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'User-Agent': 'zentinelle-js/0.1.0',
    };
    if (this.apiKey) {
      headers['X-Zentinelle-Key'] = this.apiKey;
    }
    if (this.orgId) {
      headers['X-Zentinelle-Org'] = this.orgId;
    }
    return headers;
  }

  private async handleResponse(response: Response): Promise<unknown> {
    if (response.status === 401) {
      throw new ZentinelleAuthError('Invalid or expired API key');
    }
    if (response.status === 403) {
      throw new ZentinelleAuthError('Access denied - insufficient permissions');
    }
    if (response.status === 429) {
      const retryAfter = parseInt(response.headers.get('Retry-After') ?? '60', 10);
      throw new ZentinelleRateLimitError('Rate limit exceeded', retryAfter);
    }
    if (response.status >= 500) {
      const text = await response.text();
      throw new ZentinelleConnectionError(`Server error: ${response.status} - ${text.slice(0, 200)}`);
    }
    if (!response.ok) {
      const text = await response.text();
      throw new ZentinelleError(`Request failed: ${response.status} - ${text.slice(0, 200)}`);
    }
    return response.json();
  }

  private async request<T>(
    method: 'GET' | 'POST',
    path: string,
    body?: unknown
  ): Promise<T> {
    if (!this.circuitBreaker.canExecute()) {
      if (this.failOpen) {
        return {} as T;
      }
      throw new ZentinelleConnectionError('Circuit breaker is OPEN');
    }

    const url = `${this.endpoint}/api/v1${path}`;
    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= this.retryConfig.maxRetries; attempt++) {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), this.timeout);

        const response = await fetch(url, {
          method,
          headers: this.getHeaders(),
          body: body ? JSON.stringify(body) : undefined,
          signal: controller.signal,
        });

        clearTimeout(timeoutId);
        const result = await this.handleResponse(response);
        this.circuitBreaker.recordSuccess();
        return result as T;

      } catch (error) {
        if (error instanceof ZentinelleRateLimitError) {
          this.circuitBreaker.recordSuccess();
          throw error;
        }
        if (error instanceof ZentinelleAuthError) {
          throw error;
        }

        lastError = error as Error;
        this.circuitBreaker.recordFailure();

        if (attempt >= this.retryConfig.maxRetries) {
          if (this.failOpen) {
            return {} as T;
          }
          throw new ZentinelleConnectionError(
            `Failed after ${attempt + 1} attempts: ${lastError.message}`
          );
        }

        const delay = this.retryConfig.getDelay(attempt);
        await new Promise((resolve) => setTimeout(resolve, delay));
      }
    }

    throw lastError;
  }

  // ===========================================================================
  // Registration
  // ===========================================================================

  async register(options: {
    capabilities?: string[];
    metadata?: Record<string, unknown>;
    name?: string;
  } = {}): Promise<RegisterResult> {
    const response = await this.request<{
      agent_id: string;
      api_key?: string;
      config: Record<string, unknown>;
      policies: Array<{
        id: string;
        name: string;
        type: string;
        enforcement: string;
        config: Record<string, unknown>;
        priority?: number;
      }>;
    }>('POST', '/agents/register', {
      agent_id: this.agentId,
      agent_type: this.agentType,
      capabilities: options.capabilities ?? [],
      metadata: options.metadata ?? {},
      name: options.name,
    });

    this.agentId = response.agent_id;
    this.registered = true;
    this.configCache = response.config;
    this.configCacheTime = new Date();

    return {
      agentId: response.agent_id,
      apiKey: response.api_key,
      config: response.config,
      policies: response.policies.map((p) => ({
        id: p.id,
        name: p.name,
        type: p.type as PolicyConfig['type'],
        enforcement: p.enforcement as PolicyConfig['enforcement'],
        config: p.config,
        priority: p.priority,
      })),
    };
  }

  // ===========================================================================
  // Configuration
  // ===========================================================================

  async getConfig(forceRefresh = false): Promise<ConfigResult> {
    if (!forceRefresh && this.configCache && this.configCacheTime) {
      if (Date.now() - this.configCacheTime.getTime() < this.configCacheTtl) {
        return {
          agentId: this.agentId!,
          config: this.configCache,
          policies: [],
          updatedAt: this.configCacheTime,
        };
      }
    }

    const response = await this.request<{
      agent_id: string;
      config: Record<string, unknown>;
      policies: Array<{
        id: string;
        name: string;
        type: string;
        enforcement: string;
        config: Record<string, unknown>;
      }>;
      updated_at: string;
    }>('GET', `/agents/${this.agentId}/config`);

    this.configCache = response.config;
    this.configCacheTime = new Date();

    return {
      agentId: response.agent_id,
      config: response.config,
      policies: response.policies.map((p) => ({
        id: p.id,
        name: p.name,
        type: p.type as PolicyConfig['type'],
        enforcement: p.enforcement as PolicyConfig['enforcement'],
        config: p.config,
      })),
      updatedAt: new Date(response.updated_at),
    };
  }

  // ===========================================================================
  // Secrets
  // ===========================================================================

  async getSecrets(forceRefresh = false): Promise<Record<string, string>> {
    if (!forceRefresh && this.secretsCache && this.secretsCacheTime) {
      if (Date.now() - this.secretsCacheTime.getTime() < this.secretsCacheTtl) {
        return this.secretsCache;
      }
    }

    const response = await this.request<{
      secrets: Record<string, string>;
    }>('GET', `/agents/${this.agentId}/secrets`);

    this.secretsCache = response.secrets;
    this.secretsCacheTime = new Date();

    return response.secrets;
  }

  async getSecret(key: string, defaultValue?: string): Promise<string | undefined> {
    const secrets = await this.getSecrets();
    return secrets[key] ?? defaultValue;
  }

  // ===========================================================================
  // Policy Evaluation
  // ===========================================================================

  async evaluate(
    action: string,
    options: {
      userId?: string;
      context?: Record<string, unknown>;
    } = {}
  ): Promise<EvaluateResult> {
    const response = await this.request<{
      allowed: boolean;
      reason?: string;
      policies_evaluated?: Array<{
        name: string;
        type: string;
        passed: boolean;
        message?: string;
      }>;
      warnings?: string[];
      context?: Record<string, unknown>;
    }>('POST', '/evaluate', {
      agent_id: this.agentId,
      action,
      user_id: options.userId ?? '',
      context: options.context ?? {},
    });

    return {
      allowed: response.allowed ?? true,
      reason: response.reason,
      policiesEvaluated: response.policies_evaluated ?? [],
      warnings: response.warnings ?? [],
      context: response.context ?? {},
    };
  }

  async canUseModel(model: string, provider = 'openai'): Promise<EvaluateResult> {
    return this.evaluate('model_request', {
      context: { model, provider },
    });
  }

  async canCallTool(toolName: string, userId?: string): Promise<EvaluateResult> {
    return this.evaluate('tool_call', {
      userId,
      context: { tool: toolName },
    });
  }

  // ===========================================================================
  // Usage Tracking
  // ===========================================================================

  trackUsage(usage: ModelUsage): void {
    this.emit('model_usage', {
      provider: usage.provider,
      model: usage.model,
      input_tokens: usage.inputTokens,
      output_tokens: usage.outputTokens,
      estimated_cost: usage.estimatedCost,
    });
  }

  // ===========================================================================
  // Events
  // ===========================================================================

  emit(
    eventType: string,
    payload: Record<string, unknown> = {},
    options: {
      category?: EventCategory;
      userId?: string;
    } = {}
  ): void {
    const event: Event = {
      type: eventType,
      category: options.category ?? 'telemetry',
      payload,
      timestamp: new Date().toISOString(),
      userId: options.userId,
    };

    this.eventBuffer.push(event);

    if (this.eventBuffer.length >= this.bufferSize) {
      this.flushEvents().catch(() => {});
    }
  }

  emitToolCall(options: {
    toolName: string;
    userId?: string;
    inputs?: Record<string, unknown>;
    outputs?: Record<string, unknown>;
    durationMs?: number;
  }): void {
    this.emit('tool_call', {
      tool: options.toolName,
      inputs: options.inputs ?? {},
      outputs: options.outputs ?? {},
      duration_ms: options.durationMs,
    }, {
      category: 'audit',
      userId: options.userId,
    });
  }

  emitModelRequest(options: {
    provider: string;
    model: string;
    inputTokens: number;
    outputTokens: number;
    userId?: string;
    durationMs?: number;
  }): void {
    this.emit('model_request', {
      provider: options.provider,
      model: options.model,
      input_tokens: options.inputTokens,
      output_tokens: options.outputTokens,
      duration_ms: options.durationMs,
    }, {
      category: 'telemetry',
      userId: options.userId,
    });
  }

  async flushEvents(): Promise<EventsResult | null> {
    if (this.eventBuffer.length === 0 || !this.agentId) {
      return null;
    }

    const events = this.eventBuffer;
    this.eventBuffer = [];

    try {
      const response = await this.request<{
        accepted: number;
        batch_id: string;
      }>('POST', '/events', {
        agent_id: this.agentId,
        events,
      });

      return {
        accepted: response.accepted,
        batchId: response.batch_id,
      };
    } catch (error) {
      // Re-queue events on failure
      if (this.eventBuffer.length < this.bufferSize * 2) {
        this.eventBuffer = [...events, ...this.eventBuffer];
      }
      return null;
    }
  }

  // ===========================================================================
  // Heartbeat
  // ===========================================================================

  async heartbeat(
    status: 'healthy' | 'degraded' | 'unhealthy' = 'healthy',
    metrics?: Record<string, unknown>
  ): Promise<HeartbeatResult | null> {
    if (!this.registered || !this.agentId) {
      return null;
    }

    try {
      const response = await this.request<{
        acknowledged: boolean;
        config_changed: boolean;
        next_heartbeat_seconds: number;
      }>('POST', '/heartbeat', {
        agent_id: this.agentId,
        status,
        metrics: metrics ?? {},
      });

      return {
        acknowledged: response.acknowledged,
        configChanged: response.config_changed,
        nextHeartbeatSeconds: response.next_heartbeat_seconds,
      };
    } catch {
      return null;
    }
  }

  // ===========================================================================
  // Lifecycle
  // ===========================================================================

  async shutdown(): Promise<void> {
    if (this.flushTimer) {
      clearInterval(this.flushTimer);
      this.flushTimer = null;
    }

    await this.flushEvents();
  }

  get isRegistered(): boolean {
    return this.registered;
  }

  get currentAgentId(): string | null {
    return this.agentId;
  }
}
