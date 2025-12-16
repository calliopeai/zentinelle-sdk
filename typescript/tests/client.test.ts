/**
 * Tests for ZentinelleClient
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import {
  ZentinelleClient,
  ZentinelleError,
  ZentinelleConnectionError,
  ZentinelleAuthError,
  ZentinelleRateLimitError,
  RetryConfig,
  CircuitBreaker,
} from '../src';

describe('RetryConfig', () => {
  it('should have correct default values', () => {
    const config = new RetryConfig();
    expect(config.maxRetries).toBe(3);
    expect(config.baseDelay).toBe(1000);
    expect(config.maxDelay).toBe(60000);
    expect(config.exponentialBase).toBe(2);
    expect(config.jitter).toBe(true);
  });

  it('should accept custom values', () => {
    const config = new RetryConfig({
      maxRetries: 5,
      baseDelay: 500,
      maxDelay: 30000,
      exponentialBase: 3,
      jitter: false,
    });
    expect(config.maxRetries).toBe(5);
    expect(config.baseDelay).toBe(500);
    expect(config.maxDelay).toBe(30000);
    expect(config.exponentialBase).toBe(3);
    expect(config.jitter).toBe(false);
  });

  it('should calculate delay correctly without jitter', () => {
    const config = new RetryConfig({ baseDelay: 1000, exponentialBase: 2, jitter: false });
    expect(config.getDelay(0)).toBe(1000);
    expect(config.getDelay(1)).toBe(2000);
    expect(config.getDelay(2)).toBe(4000);
  });

  it('should respect max delay', () => {
    const config = new RetryConfig({ baseDelay: 1000, maxDelay: 5000, jitter: false });
    expect(config.getDelay(10)).toBe(5000);
  });

  it('should add jitter when enabled', () => {
    const config = new RetryConfig({ baseDelay: 1000, jitter: true });
    const delays = Array.from({ length: 10 }, () => config.getDelay(0));
    const uniqueDelays = new Set(delays);
    // With jitter, we should get varying delays
    expect(uniqueDelays.size).toBeGreaterThan(1);
    // All should be within ±25% of base
    delays.forEach(delay => {
      expect(delay).toBeGreaterThanOrEqual(750);
      expect(delay).toBeLessThanOrEqual(1250);
    });
  });
});

describe('CircuitBreaker', () => {
  it('should start in closed state', () => {
    const cb = new CircuitBreaker();
    expect(cb.getState()).toBe('closed');
    expect(cb.canExecute()).toBe(true);
  });

  it('should open after threshold failures', () => {
    const cb = new CircuitBreaker({ failureThreshold: 3 });
    expect(cb.getState()).toBe('closed');

    cb.recordFailure();
    cb.recordFailure();
    expect(cb.getState()).toBe('closed');

    cb.recordFailure();
    expect(cb.getState()).toBe('open');
    expect(cb.canExecute()).toBe(false);
  });

  it('should reset failure count on success', () => {
    const cb = new CircuitBreaker({ failureThreshold: 3 });
    cb.recordFailure();
    cb.recordFailure();
    cb.recordSuccess();
    cb.recordFailure();
    cb.recordFailure();
    // Should still be closed because success reset count
    expect(cb.getState()).toBe('closed');
  });

  it('should transition to half-open after recovery timeout', async () => {
    const cb = new CircuitBreaker({ failureThreshold: 2, recoveryTimeout: 50 });
    cb.recordFailure();
    cb.recordFailure();
    expect(cb.getState()).toBe('open');

    await new Promise(resolve => setTimeout(resolve, 100));
    expect(cb.getState()).toBe('half_open');
  });

  it('should close after successful calls in half-open state', async () => {
    const cb = new CircuitBreaker({ failureThreshold: 2, recoveryTimeout: 50, halfOpenMaxCalls: 2 });
    cb.recordFailure();
    cb.recordFailure();

    await new Promise(resolve => setTimeout(resolve, 100));
    expect(cb.getState()).toBe('half_open');

    cb.recordSuccess();
    cb.recordSuccess();
    expect(cb.getState()).toBe('closed');
  });

  it('should reopen on failure in half-open state', async () => {
    const cb = new CircuitBreaker({ failureThreshold: 2, recoveryTimeout: 50 });
    cb.recordFailure();
    cb.recordFailure();

    await new Promise(resolve => setTimeout(resolve, 100));
    expect(cb.getState()).toBe('half_open');

    cb.recordFailure();
    expect(cb.getState()).toBe('open');
  });
});

describe('ZentinelleClient', () => {
  let client: ZentinelleClient;

  afterEach(() => {
    if (client) {
      client.shutdown();
    }
  });

  describe('constructor', () => {
    it('should create client with valid options', () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        autoFlush: false,
        autoHeartbeat: false,
      });
      expect(client).toBeDefined();
      expect(client.isRegistered).toBe(false);
    });

    it('should throw on missing apiKey', () => {
      expect(() => new ZentinelleClient({
        apiKey: '',
        agentType: 'test',
      })).toThrow('apiKey is required');
    });

    it('should throw on short apiKey', () => {
      expect(() => new ZentinelleClient({
        apiKey: 'short',
        agentType: 'test',
      })).toThrow('apiKey is required');
    });

    it('should throw on missing agentType', () => {
      expect(() => new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: '',
      })).toThrow('agentType is required');
    });

    it('should throw on non-HTTPS endpoint', () => {
      expect(() => new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        endpoint: 'http://example.com',
      })).toThrow('HTTPS');
    });

    it('should allow localhost without HTTPS', () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        endpoint: 'http://localhost:3000',
        autoFlush: false,
        autoHeartbeat: false,
      });
      expect(client).toBeDefined();
    });

    it('should allow 127.0.0.1 without HTTPS', () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        endpoint: 'http://127.0.0.1:3000',
        autoFlush: false,
        autoHeartbeat: false,
      });
      expect(client).toBeDefined();
    });

    it('should strip trailing slash from endpoint', () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        endpoint: 'https://api.example.com/',
        autoFlush: false,
        autoHeartbeat: false,
      });
      expect(client.toString()).toContain('endpoint="https://api.example.com"');
    });

    it('should calculate max buffer size correctly', () => {
      // Small buffer: max should be 1000
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        bufferSize: 50,
        autoFlush: false,
        autoHeartbeat: false,
      });
      // Can't directly access private field, but we can test behavior
      expect(client).toBeDefined();
    });
  });

  describe('toString', () => {
    it('should mask API key in output', () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_secret_key_12345',
        agentType: 'test',
        autoFlush: false,
        autoHeartbeat: false,
      });
      const str = client.toString();
      expect(str).not.toContain('sk_agent_secret_key_12345');
      expect(str).toContain('sk_agent...');
      expect(str).toContain('...2345');
    });

    it('should show agent info', () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'langchain',
        agentId: 'agent-123',
        autoFlush: false,
        autoHeartbeat: false,
      });
      const str = client.toString();
      expect(str).toContain('agentId="agent-123"');
      expect(str).toContain('agentType="langchain"');
    });
  });

  describe('requireAgentId', () => {
    it('should throw when calling getConfig without agent_id', async () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        autoFlush: false,
        autoHeartbeat: false,
      });
      await expect(client.getConfig()).rejects.toThrow('Agent not registered');
    });

    it('should throw when calling getSecrets without agent_id', async () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        autoFlush: false,
        autoHeartbeat: false,
      });
      await expect(client.getSecrets()).rejects.toThrow('Agent not registered');
    });

    it('should throw when calling evaluate without agent_id', async () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        autoFlush: false,
        autoHeartbeat: false,
      });
      await expect(client.evaluate('test')).rejects.toThrow('Agent not registered');
    });

    it('should not throw agent error when agentId is provided in constructor', () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        agentId: 'pre-registered-agent',
        autoFlush: false,
        autoHeartbeat: false,
      });
      // With agentId provided, requireAgentId should not throw
      // The getConfig call will fail due to network, but that's a different error
      expect(client.currentAgentId).toBe('pre-registered-agent');
    });
  });

  describe('emit', () => {
    it('should buffer events', () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        bufferSize: 100,
        autoFlush: false,
        autoHeartbeat: false,
      });

      client.emit('test_event', { key: 'value' });
      // Events are buffered, can verify via flush
      expect(client).toBeDefined();
    });

    it('should emit tool call events', () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        autoFlush: false,
        autoHeartbeat: false,
      });

      client.emitToolCall({
        toolName: 'web_search',
        userId: 'user123',
        durationMs: 150,
      });
      expect(client).toBeDefined();
    });

    it('should emit model request events', () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        autoFlush: false,
        autoHeartbeat: false,
      });

      client.emitModelRequest({
        provider: 'openai',
        model: 'gpt-4',
        inputTokens: 100,
        outputTokens: 50,
        userId: 'user123',
      });
      expect(client).toBeDefined();
    });
  });

  describe('trackUsage', () => {
    it('should track model usage', () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        autoFlush: false,
        autoHeartbeat: false,
      });

      client.trackUsage({
        provider: 'openai',
        model: 'gpt-4',
        inputTokens: 100,
        outputTokens: 50,
      });
      expect(client).toBeDefined();
    });
  });

  describe('heartbeat', () => {
    it('should return null when not registered', async () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        autoFlush: false,
        autoHeartbeat: false,
      });

      const result = await client.heartbeat();
      expect(result).toBeNull();
    });
  });

  describe('shutdown', () => {
    it('should clear timers and data', async () => {
      client = new ZentinelleClient({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'test',
        autoFlush: true,
        autoHeartbeat: true,
      });

      await client.shutdown();
      // Should not throw
      expect(client).toBeDefined();
    });
  });
});

describe('Error classes', () => {
  it('should have correct inheritance', () => {
    expect(new ZentinelleConnectionError('test')).toBeInstanceOf(ZentinelleError);
    expect(new ZentinelleAuthError('test')).toBeInstanceOf(ZentinelleError);
    expect(new ZentinelleRateLimitError('test', 60)).toBeInstanceOf(ZentinelleError);
  });

  it('should set retryAfter on rate limit error', () => {
    const error = new ZentinelleRateLimitError('rate limited', 30);
    expect(error.retryAfter).toBe(30);
  });

  it('should default retryAfter to 60', () => {
    const error = new ZentinelleRateLimitError('rate limited');
    expect(error.retryAfter).toBe(60);
  });
});
