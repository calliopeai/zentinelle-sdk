/**
 * Zentinelle SDK Client - Main client for AI agent governance.
 */

const VERSION = '0.1.0';

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
  /** Enable automatic heartbeats (default: true) */
  autoHeartbeat?: boolean;
  /** Interval between heartbeats in milliseconds (default: 60000) */
  heartbeatInterval?: number;
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
  private readonly maxBufferSize: number;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private readonly heartbeatInterval: number;
  private flushInProgress = false;

  private configCache: Record<string, unknown> | null = null;
  private configCacheTime: Date | null = null;
  private policiesCache: PolicyConfig[] = [];
  private readonly configCacheTtl = 300000; // 5 minutes

  private secretsCache: Record<string, string> | null = null;
  private secretsCacheTime: Date | null = null;
  private readonly secretsCacheTtl = 60000; // 1 minute

  private registered = false;

  constructor(options: ZentinelleClientOptions) {
    // Validate required parameters
    if (!options.apiKey || options.apiKey.length < 10) {
      throw new Error('apiKey is required and must be valid');
    }
    // Validate API key format (should start with known prefixes)
    const validPrefixes = ['sk_agent_', 'sk_test_', 'sk_live_', 'znt_'];
    if (!validPrefixes.some(prefix => options.apiKey.startsWith(prefix))) {
      console.warn(
        '[Zentinelle] API key does not match expected format (sk_agent_*, sk_test_*, sk_live_*, znt_*). ' +
        'This may indicate an invalid key.'
      );
    }
    if (!options.agentType) {
      throw new Error('agentType is required');
    }

    this.endpoint = (options.endpoint ?? 'https://api.zentinelle.ai').replace(/\/$/, '');
    // Enforce HTTPS for security (API keys are transmitted in headers)
    // Allow localhost/127.0.0.1 for local development
    const isLocalhost = this.endpoint.includes('localhost') || this.endpoint.includes('127.0.0.1');
    if (!this.endpoint.startsWith('https://') && !isLocalhost) {
      throw new Error('endpoint must use HTTPS for security (localhost excepted)');
    }
    this.apiKey = options.apiKey;
    this.agentType = options.agentType;
    this.agentId = options.agentId ?? null;
    this.orgId = options.orgId;
    this.timeout = options.timeout ?? 30000;
    this.failOpen = options.failOpen ?? false;
    this.bufferSize = options.bufferSize ?? 100;
    // Maximum buffer size to prevent memory leaks (10x normal or 1000, whichever is larger)
    this.maxBufferSize = Math.max(this.bufferSize * 10, 1000);

    this.retryConfig = options.retryConfig ?? new RetryConfig();
    this.circuitBreaker = new CircuitBreaker({
      failureThreshold: options.circuitBreakerThreshold ?? 5,
      recoveryTimeout: options.circuitBreakerRecovery ?? 30000,
    });
    this.heartbeatInterval = options.heartbeatInterval ?? 60000;

    // Start auto-flush if enabled
    if (options.autoFlush !== false) {
      const interval = options.flushInterval ?? 5000;
      this.flushTimer = setInterval(() => {
        if (this.registered) {
          this.flushEvents().catch((err) => {
            console.warn('[Zentinelle] Background event flush failed:', err?.message ?? String(err));
          });
        }
      }, interval);
      // Unref timer to allow process to exit if this is the only thing keeping it alive
      if (typeof this.flushTimer === 'object' && 'unref' in this.flushTimer) {
        (this.flushTimer as NodeJS.Timeout).unref();
      }
    }

    // Start auto-heartbeat if enabled
    if (options.autoHeartbeat !== false) {
      this.heartbeatTimer = setInterval(() => {
        if (this.registered) {
          this.heartbeat().then((result) => {
            if (result?.configChanged) {
              this.getConfig(true).catch((err) => {
                console.warn('[Zentinelle] Background config refresh failed:', err?.message ?? String(err));
              });
            }
          }).catch((err) => {
            console.debug('[Zentinelle] Background heartbeat failed:', err?.message ?? String(err));
          });
        }
      }, this.heartbeatInterval);
      // Unref timer to allow process to exit if this is the only thing keeping it alive
      if (typeof this.heartbeatTimer === 'object' && 'unref' in this.heartbeatTimer) {
        (this.heartbeatTimer as NodeJS.Timeout).unref();
      }
    }
  }

  // ===========================================================================
  // HTTP Helpers
  // ===========================================================================

  private getHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'User-Agent': `zentinelle-js/${VERSION}`,
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
    body?: unknown,
    options?: { isEvaluateRequest?: boolean }
  ): Promise<T> {
    if (!this.circuitBreaker.canExecute()) {
      if (this.failOpen) {
        console.warn('[Zentinelle] Circuit breaker OPEN, failing open');
        return this.createFailOpenResponse<T>(options?.isEvaluateRequest);
      }
      throw new ZentinelleConnectionError('Circuit breaker is OPEN');
    }

    const url = `${this.endpoint}/api/v1${path}`;
    let lastError: Error | null = null;

    for (let attempt = 0; attempt <= this.retryConfig.maxRetries; attempt++) {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), this.timeout);

      try {
        const response = await fetch(url, {
          method,
          headers: this.getHeaders(),
          body: body ? JSON.stringify(body) : undefined,
          signal: controller.signal,
        });

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
            console.warn(`[Zentinelle] Request failed after ${attempt + 1} attempts, failing open: ${lastError.message}`);
            return this.createFailOpenResponse<T>(options?.isEvaluateRequest);
          }
          throw new ZentinelleConnectionError(
            `Failed after ${attempt + 1} attempts: ${lastError.message}`
          );
        }

        const delay = this.retryConfig.getDelay(attempt);
        await new Promise((resolve) => setTimeout(resolve, delay));
      } finally {
        // Always clear timeout to prevent resource leak
        clearTimeout(timeoutId);
      }
    }

    // This should be unreachable, but guard against edge cases
    if (lastError) {
      throw lastError;
    }
    throw new ZentinelleConnectionError(`Request to ${path} failed unexpectedly`);
  }

  private createFailOpenResponse<T>(isEvaluateRequest?: boolean): T {
    if (isEvaluateRequest) {
      // Return a properly marked fail-open response for evaluate requests
      return {
        allowed: true,
        reason: 'fail_open',
        fail_open: true,
        policies_evaluated: [],
        warnings: ['Service unavailable - fail-open mode active'],
        context: {},
      } as unknown as T;
    }
    // For other requests, return empty object (caller should handle)
    return { fail_open: true } as T;
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
    this.policiesCache = response.policies.map((p) => ({
      id: p.id,
      name: p.name,
      type: p.type as PolicyConfig['type'],
      enforcement: p.enforcement as PolicyConfig['enforcement'],
      config: p.config,
      priority: p.priority,
    }));

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
  // Helpers
  // ===========================================================================

  private requireAgentId(): void {
    if (!this.agentId) {
      throw new ZentinelleError(
        'Agent not registered. Call register() first or provide agentId in constructor.'
      );
    }
  }

  // ===========================================================================
  // Configuration
  // ===========================================================================

  async getConfig(forceRefresh = false): Promise<ConfigResult> {
    this.requireAgentId();
    if (!forceRefresh && this.configCache && this.configCacheTime) {
      if (Date.now() - this.configCacheTime.getTime() < this.configCacheTtl) {
        return {
          agentId: this.agentId!,
          config: { ...this.configCache },
          policies: [...this.policiesCache],
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
    this.policiesCache = response.policies.map((p) => ({
      id: p.id,
      name: p.name,
      type: p.type as PolicyConfig['type'],
      enforcement: p.enforcement as PolicyConfig['enforcement'],
      config: p.config,
    }));

    return {
      agentId: response.agent_id,
      config: response.config,
      policies: this.policiesCache,
      updatedAt: new Date(response.updated_at),
    };
  }

  // ===========================================================================
  // Secrets
  // ===========================================================================

  async getSecrets(forceRefresh = false): Promise<Record<string, string>> {
    this.requireAgentId();
    if (!forceRefresh && this.secretsCache && this.secretsCacheTime) {
      if (Date.now() - this.secretsCacheTime.getTime() < this.secretsCacheTtl) {
        // Return a copy to prevent external mutation
        return { ...this.secretsCache };
      }
    }

    const response = await this.request<{
      secrets: Record<string, string>;
    }>('GET', `/agents/${this.agentId}/secrets`);

    this.secretsCache = response.secrets;
    this.secretsCacheTime = new Date();

    // Return a copy to prevent external mutation
    return { ...response.secrets };
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
    this.requireAgentId();
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
      fail_open?: boolean;
    }>('POST', '/evaluate', {
      agent_id: this.agentId,
      action,
      user_id: options.userId ?? '',
      context: options.context ?? {},
    }, { isEvaluateRequest: true });

    // Critical: validate that 'allowed' field is present (unless fail-open)
    // Never default to true - this would bypass security
    if (!response.fail_open && (response.allowed === undefined || response.allowed === null)) {
      throw new ZentinelleError('Invalid response: missing required "allowed" field');
    }

    return {
      allowed: response.allowed,
      reason: response.reason,
      policiesEvaluated: response.policies_evaluated ?? [],
      warnings: response.warnings ?? [],
      context: response.context ?? {},
      failOpen: response.fail_open ?? false,
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

    // Enforce max buffer size to prevent memory leaks
    if (this.eventBuffer.length >= this.maxBufferSize) {
      const dropped = this.eventBuffer.length - this.maxBufferSize + 1;
      this.eventBuffer = this.eventBuffer.slice(dropped);
      console.warn(`[Zentinelle] Event buffer at max capacity, dropped ${dropped} oldest events`);
    }

    this.eventBuffer.push(event);

    if (this.eventBuffer.length >= this.bufferSize) {
      this.flushEvents().catch((err) => {
        console.warn('[Zentinelle] Buffer flush failed:', err?.message ?? String(err));
      });
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

    // Prevent concurrent flushes
    if (this.flushInProgress) {
      return null;
    }
    this.flushInProgress = true;

    // Atomically swap buffer
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
      // Re-queue events on failure (check against maxBufferSize to avoid overflow)
      if (this.eventBuffer.length + events.length <= this.maxBufferSize) {
        this.eventBuffer = [...events, ...this.eventBuffer];
      } else {
        console.warn(`[Zentinelle] Failed to flush ${events.length} events and buffer is full, events dropped`);
      }
      return null;
    } finally {
      this.flushInProgress = false;
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
    } catch (error) {
      console.debug('[Zentinelle] Heartbeat failed:', error instanceof Error ? error.message : String(error));
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

    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }

    // Flush remaining events
    await this.flushEvents();

    // Clear sensitive data from memory
    this.secretsCache = null;
    this.secretsCacheTime = null;
    this.configCache = null;
    this.configCacheTime = null;
    this.policiesCache = [];
  }

  get isRegistered(): boolean {
    return this.registered;
  }

  get currentAgentId(): string | null {
    return this.agentId;
  }

  /**
   * Returns a string representation of the client with masked API key.
   */
  toString(): string {
    const maskedKey = this.apiKey.length > 12
      ? `${this.apiKey.slice(0, 8)}...${this.apiKey.slice(-4)}`
      : '***';
    return `ZentinelleClient(agentId="${this.agentId}", agentType="${this.agentType}", endpoint="${this.endpoint}", apiKey="${maskedKey}")`;
  }
}
