import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { ZentinelleMiddleware, withGovernance } from '../src/middleware';

// Mock the zentinelle module
vi.mock('zentinelle', () => {
  const mockEvaluate = vi.fn();
  const mockEmit = vi.fn();
  const mockEmitModelRequest = vi.fn();
  const mockEmitToolCall = vi.fn();
  const mockShutdown = vi.fn().mockResolvedValue(undefined);

  return {
    ZentinelleClient: vi.fn().mockImplementation(() => ({
      evaluate: mockEvaluate,
      emit: mockEmit,
      emitModelRequest: mockEmitModelRequest,
      emitToolCall: mockEmitToolCall,
      shutdown: mockShutdown,
    })),
    __mockEvaluate: mockEvaluate,
    __mockEmit: mockEmit,
    __mockEmitModelRequest: mockEmitModelRequest,
    __mockShutdown: mockShutdown,
  };
});

// Get mocks from the mocked module
import { ZentinelleClient } from 'zentinelle';

function getMocks() {
  const mod = vi.mocked(ZentinelleClient);
  // The last instance created
  const instance = mod.mock.results[mod.mock.results.length - 1]?.value;
  return {
    clientConstructor: mod,
    evaluate: instance?.evaluate as ReturnType<typeof vi.fn>,
    emit: instance?.emit as ReturnType<typeof vi.fn>,
    emitModelRequest: instance?.emitModelRequest as ReturnType<typeof vi.fn>,
    shutdown: instance?.shutdown as ReturnType<typeof vi.fn>,
  };
}

function createRequest(url: string, options: RequestInit = {}): Request {
  return new Request(url, {
    method: options.method ?? 'POST',
    headers: new Headers({
      'content-type': 'application/json',
      'user-agent': 'test-agent',
      ...(options.headers as Record<string, string> ?? {}),
    }),
    ...(options.body ? { body: options.body } : {}),
  });
}

describe('ZentinelleMiddleware', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('constructor', () => {
    it('should create a ZentinelleClient with provided options', () => {
      new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'nextjs-chat',
        endpoint: 'https://custom.zentinelle.ai',
        failOpen: true,
      });

      expect(ZentinelleClient).toHaveBeenCalledWith({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'nextjs-chat',
        endpoint: 'https://custom.zentinelle.ai',
        failOpen: true,
      });
    });

    it('should default agentType to nextjs', () => {
      new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });

      expect(ZentinelleClient).toHaveBeenCalledWith(
        expect.objectContaining({ agentType: 'nextjs' })
      );
    });

    it('should default failOpen to false', () => {
      new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });

      expect(ZentinelleClient).toHaveBeenCalledWith(
        expect.objectContaining({ failOpen: false })
      );
    });
  });

  describe('evaluate', () => {
    it('should evaluate a request and return allowed result', async () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();
      mocks.evaluate.mockResolvedValue({
        allowed: true,
        warnings: [],
      });

      const req = createRequest('https://example.com/api/chat');
      const result = await middleware.evaluate(req);

      expect(result.allowed).toBe(true);
      expect(result.warnings).toEqual([]);
    });

    it('should evaluate a request and return blocked result', async () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();
      mocks.evaluate.mockResolvedValue({
        allowed: false,
        reason: 'Rate limit exceeded',
        warnings: [],
      });

      const req = createRequest('https://example.com/api/chat');
      const result = await middleware.evaluate(req);

      expect(result.allowed).toBe(false);
      expect(result.reason).toBe('Rate limit exceeded');
    });

    it('should extract userId via getUserId callback', async () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
        getUserId: (req) => req.headers.get('x-user-id') ?? undefined,
      });
      const mocks = getMocks();
      mocks.evaluate.mockResolvedValue({
        allowed: true,
        warnings: [],
      });

      const req = createRequest('https://example.com/api/chat', {
        headers: { 'x-user-id': 'user-42' },
      });
      const result = await middleware.evaluate(req);

      expect(result.userId).toBe('user-42');
      expect(mocks.evaluate).toHaveBeenCalledWith(
        'api_request',
        expect.objectContaining({ userId: 'user-42' })
      );
    });

    it('should include request metadata in context', async () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();
      mocks.evaluate.mockResolvedValue({
        allowed: true,
        warnings: [],
      });

      const req = createRequest('https://example.com/api/chat', {
        method: 'POST',
      });
      await middleware.evaluate(req);

      expect(mocks.evaluate).toHaveBeenCalledWith(
        'api_request',
        expect.objectContaining({
          context: expect.objectContaining({
            method: 'POST',
            path: '/api/chat',
          }),
        })
      );
    });

    it('should use custom action name', async () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
        action: 'chat_completion',
      });
      const mocks = getMocks();
      mocks.evaluate.mockResolvedValue({
        allowed: true,
        warnings: [],
      });

      const req = createRequest('https://example.com/api/chat');
      await middleware.evaluate(req);

      expect(mocks.evaluate).toHaveBeenCalledWith(
        'chat_completion',
        expect.anything()
      );
    });

    it('should merge custom context from getContext callback', async () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
        getContext: () => ({ customField: 'value', tier: 'premium' }),
      });
      const mocks = getMocks();
      mocks.evaluate.mockResolvedValue({
        allowed: true,
        warnings: [],
      });

      const req = createRequest('https://example.com/api/chat');
      await middleware.evaluate(req);

      expect(mocks.evaluate).toHaveBeenCalledWith(
        'api_request',
        expect.objectContaining({
          context: expect.objectContaining({
            customField: 'value',
            tier: 'premium',
          }),
        })
      );
    });

    it('should fail open when configured and evaluation throws', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
        failOpen: true,
      });
      const mocks = getMocks();
      mocks.evaluate.mockRejectedValue(new Error('connection refused'));

      const req = createRequest('https://example.com/api/chat');
      const result = await middleware.evaluate(req);

      expect(result.allowed).toBe(true);
      expect(result.warnings).toContain(
        'Policy evaluation failed, allowing request (fail-open mode)'
      );
      warnSpy.mockRestore();
    });

    it('should propagate error when failOpen is false and evaluation throws', async () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
        failOpen: false,
      });
      const mocks = getMocks();
      mocks.evaluate.mockRejectedValue(new Error('connection refused'));

      const req = createRequest('https://example.com/api/chat');
      await expect(middleware.evaluate(req)).rejects.toThrow('connection refused');
    });
  });

  describe('guard', () => {
    it('should return null when request is allowed', async () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();
      mocks.evaluate.mockResolvedValue({
        allowed: true,
        warnings: [],
      });

      const req = createRequest('https://example.com/api/chat');
      const response = await middleware.guard(req);
      expect(response).toBeNull();
    });

    it('should return 403 Response when request is blocked', async () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();
      mocks.evaluate.mockResolvedValue({
        allowed: false,
        reason: 'User not authorized',
        warnings: [],
      });

      const req = createRequest('https://example.com/api/chat');
      const response = await middleware.guard(req);

      expect(response).toBeInstanceOf(Response);
      expect(response!.status).toBe(403);

      const body = await response!.json();
      expect(body.error).toBe('Request blocked by policy');
      expect(body.reason).toBe('User not authorized');
    });

    it('should log warnings when request is allowed with warnings', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();
      mocks.evaluate.mockResolvedValue({
        allowed: true,
        warnings: ['approaching rate limit', 'high cost usage'],
      });

      const req = createRequest('https://example.com/api/chat');
      await middleware.guard(req);

      expect(warnSpy).toHaveBeenCalledWith(
        '[Zentinelle] approaching rate limit'
      );
      expect(warnSpy).toHaveBeenCalledWith(
        '[Zentinelle] high cost usage'
      );
      warnSpy.mockRestore();
    });
  });

  describe('trackCompletion', () => {
    it('should emit model request event with usage data', () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();

      middleware.trackCompletion(
        { usage: { promptTokens: 100, completionTokens: 50 } },
        'user-42',
        'gpt-4o',
        'openai'
      );

      expect(mocks.emitModelRequest).toHaveBeenCalledWith({
        provider: 'openai',
        model: 'gpt-4o',
        inputTokens: 100,
        outputTokens: 50,
        userId: 'user-42',
      });
    });

    it('should auto-detect provider from model name', () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();

      middleware.trackCompletion(
        { usage: { promptTokens: 200, completionTokens: 100 } },
        undefined,
        'claude-3-opus'
      );

      expect(mocks.emitModelRequest).toHaveBeenCalledWith(
        expect.objectContaining({ provider: 'anthropic' })
      );
    });

    it('should not emit when usage is undefined', () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();

      middleware.trackCompletion({}, 'user-42');

      expect(mocks.emitModelRequest).not.toHaveBeenCalled();
    });

    it('should default provider to unknown when model is unrecognized', () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();

      middleware.trackCompletion(
        { usage: { promptTokens: 50, completionTokens: 25 } },
        undefined,
        'custom-model-v1'
      );

      expect(mocks.emitModelRequest).toHaveBeenCalledWith(
        expect.objectContaining({ provider: 'unknown' })
      );
    });

    it('should detect various providers correctly', () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();
      const usage = { promptTokens: 10, completionTokens: 5 };

      const providerTests = [
        { model: 'gpt-4o', expected: 'openai' },
        { model: 'claude-3-haiku', expected: 'anthropic' },
        { model: 'gemini-pro', expected: 'google' },
        { model: 'mistral-large', expected: 'mistral' },
        { model: 'command-r-plus', expected: 'cohere' },
        { model: 'llama-3-70b', expected: 'meta' },
        { model: 'deepseek-coder', expected: 'deepseek' },
      ];

      for (const { model, expected } of providerTests) {
        mocks.emitModelRequest.mockClear();
        middleware.trackCompletion({ usage }, undefined, model);
        expect(mocks.emitModelRequest).toHaveBeenCalledWith(
          expect.objectContaining({ provider: expected })
        );
      }
    });
  });

  describe('emit', () => {
    it('should emit custom event through the client', () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();

      middleware.emit('custom_action', { data: 'value' }, {
        userId: 'user-42',
        category: 'audit',
      });

      expect(mocks.emit).toHaveBeenCalledWith(
        'custom_action',
        { data: 'value' },
        { category: 'audit', userId: 'user-42' }
      );
    });

    it('should default category to telemetry', () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();

      middleware.emit('test_event', { key: 'val' });

      expect(mocks.emit).toHaveBeenCalledWith(
        'test_event',
        { key: 'val' },
        { category: 'telemetry', userId: undefined }
      );
    });
  });

  describe('getClient', () => {
    it('should return the underlying ZentinelleClient', () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const client = middleware.getClient();
      expect(client).toBeDefined();
      expect(client.evaluate).toBeDefined();
    });
  });

  describe('shutdown', () => {
    it('should delegate to client shutdown', async () => {
      const middleware = new ZentinelleMiddleware({
        apiKey: 'sk_agent_test_key_123',
      });
      const mocks = getMocks();

      await middleware.shutdown();

      expect(mocks.shutdown).toHaveBeenCalled();
    });
  });
});

describe('withGovernance', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('should block request when policy denies it', async () => {
    // The withGovernance HOF creates its own ZentinelleMiddleware internally.
    // Since ZentinelleClient is mocked, the evaluate call on the internal
    // middleware will use the mock.

    const governance = withGovernance({
      apiKey: 'sk_agent_test_key_123',
    });

    // Get the mock from the newly created client
    const mod = vi.mocked(ZentinelleClient);
    const instance = mod.mock.results[mod.mock.results.length - 1]?.value;
    // First evaluate call is guard() which returns blocked
    instance.evaluate.mockResolvedValue({
      allowed: false,
      reason: 'Not authorized',
      warnings: [],
    });

    const handler = vi.fn().mockResolvedValue(new Response('OK'));
    const wrappedHandler = governance(handler);

    const req = createRequest('https://example.com/api/chat');
    const response = await wrappedHandler(req);

    expect(response.status).toBe(403);
    expect(handler).not.toHaveBeenCalled();
  });

  it('should pass through when policy allows', async () => {
    const governance = withGovernance({
      apiKey: 'sk_agent_test_key_123',
    });

    const mod = vi.mocked(ZentinelleClient);
    const instance = mod.mock.results[mod.mock.results.length - 1]?.value;
    // guard() calls evaluate() -> allowed, then wrappedHandler calls evaluate() again
    instance.evaluate.mockResolvedValue({
      allowed: true,
      warnings: [],
      userId: 'user-42',
    });

    const handler = vi.fn().mockResolvedValue(new Response('OK'));
    const wrappedHandler = governance(handler);

    const req = createRequest('https://example.com/api/chat');
    const response = await wrappedHandler(req);

    expect(response.status).toBe(200);
    expect(handler).toHaveBeenCalled();
  });
});
