import { describe, it, expect, vi, beforeEach } from 'vitest';
import { PolicyViolationError } from '../src/errors';

// vi.hoisted ensures these are available when vi.mock factories run (hoisted above imports)
const {
  mockEvaluate,
  mockEmit,
  mockEmitModelRequest,
  mockEmitToolCall,
  mockTrackUsage,
  mockRegister,
  mockShutdown,
  mockClientConstructor,
  mockGenerateText,
  mockStreamText,
  mockGenerateObject,
  mockStreamObject,
} = vi.hoisted(() => {
  const mockEvaluate = vi.fn();
  const mockEmit = vi.fn();
  const mockEmitModelRequest = vi.fn();
  const mockEmitToolCall = vi.fn();
  const mockTrackUsage = vi.fn();
  const mockRegister = vi.fn();
  const mockShutdown = vi.fn().mockResolvedValue(undefined);
  const mockClientConstructor = vi.fn().mockImplementation(() => ({
    evaluate: mockEvaluate,
    emit: mockEmit,
    emitModelRequest: mockEmitModelRequest,
    emitToolCall: mockEmitToolCall,
    trackUsage: mockTrackUsage,
    register: mockRegister,
    shutdown: mockShutdown,
  }));
  const mockGenerateText = vi.fn();
  const mockStreamText = vi.fn();
  const mockGenerateObject = vi.fn();
  const mockStreamObject = vi.fn();
  return {
    mockEvaluate,
    mockEmit,
    mockEmitModelRequest,
    mockEmitToolCall,
    mockTrackUsage,
    mockRegister,
    mockShutdown,
    mockClientConstructor,
    mockGenerateText,
    mockStreamText,
    mockGenerateObject,
    mockStreamObject,
  };
});

vi.mock('zentinelle', () => ({
  ZentinelleClient: mockClientConstructor,
}));

// Mock the 'ai' module. createGovernedAI uses `import('ai')` dynamically,
// but vi.mock intercepts all import/require calls.
vi.mock('ai', () => ({
  generateText: mockGenerateText,
  streamText: mockStreamText,
  generateObject: mockGenerateObject,
  streamObject: mockStreamObject,
}));

import { createGovernedAI } from '../src/governed';

function createMockModel(modelId: string) {
  return { modelId, provider: 'test' } as any;
}

describe('createGovernedAI', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('factory', () => {
    it('should create governed AI instance with all methods', () => {
      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      expect(governed.generateText).toBeDefined();
      expect(governed.streamText).toBeDefined();
      expect(governed.generateObject).toBeDefined();
      expect(governed.tool).toBeDefined();
      expect(governed.register).toBeDefined();
      expect(governed.shutdown).toBeDefined();
      expect(governed.client).toBeDefined();
    });

    it('should default agentType to vercel-ai', () => {
      createGovernedAI({ apiKey: 'sk_agent_test_key_123' });

      expect(mockClientConstructor).toHaveBeenCalledWith(
        expect.objectContaining({ agentType: 'vercel-ai' })
      );
    });

    it('should pass through custom options', () => {
      createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'custom-agent',
        endpoint: 'https://my-zentinelle.example.com',
        failOpen: true,
      });

      expect(mockClientConstructor).toHaveBeenCalledWith({
        apiKey: 'sk_agent_test_key_123',
        agentType: 'custom-agent',
        endpoint: 'https://my-zentinelle.example.com',
        failOpen: true,
      });
    });
  });

  describe('generateText', () => {
    it('should evaluate policy before calling generateText', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });
      mockGenerateText.mockResolvedValue({
        text: 'Hello!',
        usage: { promptTokens: 10, completionTokens: 5 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.generateText({
        model: createMockModel('gpt-4o'),
        prompt: 'Say hello',
        userId: 'user-42',
      });

      expect(mockEvaluate).toHaveBeenCalledWith('model_request', {
        userId: 'user-42',
        context: expect.objectContaining({
          model: 'gpt-4o',
          provider: 'openai',
          operation: 'generateText',
        }),
      });
    });

    it('should throw PolicyViolationError when input policy blocks', async () => {
      mockEvaluate.mockResolvedValue({
        allowed: false,
        reason: 'Model not permitted',
        warnings: [],
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await expect(
        governed.generateText({
          model: createMockModel('gpt-4o'),
          prompt: 'Hello',
        })
      ).rejects.toThrow(PolicyViolationError);
    });

    it('should not call the underlying generateText when blocked', async () => {
      mockEvaluate.mockResolvedValue({
        allowed: false,
        reason: 'blocked',
        warnings: [],
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      try {
        await governed.generateText({
          model: createMockModel('gpt-4o'),
          prompt: 'Hello',
        });
      } catch {
        // expected
      }

      expect(mockGenerateText).not.toHaveBeenCalled();
    });

    it('should track usage after successful generation', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });
      mockGenerateText.mockResolvedValue({
        text: 'Response text',
        usage: { promptTokens: 100, completionTokens: 50 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
        trackUsage: true,
      });

      await governed.generateText({
        model: createMockModel('gpt-4o'),
        prompt: 'Hello',
        userId: 'user-42',
      });

      expect(mockTrackUsage).toHaveBeenCalledWith({
        provider: 'openai',
        model: 'gpt-4o',
        inputTokens: 100,
        outputTokens: 50,
      });
      expect(mockEmitModelRequest).toHaveBeenCalledWith(
        expect.objectContaining({
          provider: 'openai',
          model: 'gpt-4o',
          inputTokens: 100,
          outputTokens: 50,
          userId: 'user-42',
          durationMs: expect.any(Number),
        })
      );
    });

    it('should not track usage when trackUsage is false', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });
      mockGenerateText.mockResolvedValue({
        text: 'Response text',
        usage: { promptTokens: 100, completionTokens: 50 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
        trackUsage: false,
      });

      await governed.generateText({
        model: createMockModel('gpt-4o'),
        prompt: 'Hello',
      });

      expect(mockTrackUsage).not.toHaveBeenCalled();
      expect(mockEmitModelRequest).not.toHaveBeenCalled();
    });

    it('should skip input evaluation when evaluateInput is false', async () => {
      mockGenerateText.mockResolvedValue({
        text: 'Response',
        usage: { promptTokens: 10, completionTokens: 5 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
        evaluateInput: false,
      });

      await governed.generateText({
        model: createMockModel('gpt-4o'),
        prompt: 'Hello',
      });

      // evaluate should not have been called at all
      expect(mockEvaluate).not.toHaveBeenCalled();
    });

    it('should evaluate output when evaluateOutput is true', async () => {
      // First call: input evaluation (allowed)
      // Second call: output evaluation (allowed)
      mockEvaluate
        .mockResolvedValueOnce({ allowed: true, warnings: [] })
        .mockResolvedValueOnce({ allowed: true, warnings: [] });

      mockGenerateText.mockResolvedValue({
        text: 'Generated text response',
        usage: { promptTokens: 10, completionTokens: 20 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
        evaluateOutput: true,
      });

      await governed.generateText({
        model: createMockModel('gpt-4o'),
        prompt: 'Hello',
        userId: 'user-42',
      });

      // Second evaluate call should be for model_response
      expect(mockEvaluate).toHaveBeenCalledWith('model_response', {
        userId: 'user-42',
        context: expect.objectContaining({
          model: 'gpt-4o',
          outputLength: 23, // 'Generated text response'.length
        }),
      });
    });

    it('should throw when output evaluation blocks', async () => {
      mockEvaluate
        .mockResolvedValueOnce({ allowed: true, warnings: [] })
        .mockResolvedValueOnce({
          allowed: false,
          reason: 'Output contains PII',
          warnings: [],
        });

      mockGenerateText.mockResolvedValue({
        text: 'SSN: 123-45-6789',
        usage: { promptTokens: 10, completionTokens: 5 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
        evaluateOutput: true,
      });

      await expect(
        governed.generateText({
          model: createMockModel('gpt-4o'),
          prompt: 'Tell me SSNs',
        })
      ).rejects.toThrow(PolicyViolationError);
    });

    it('should log warnings from policy evaluation', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
      mockEvaluate.mockResolvedValue({
        allowed: true,
        warnings: ['approaching rate limit'],
      });
      mockGenerateText.mockResolvedValue({
        text: 'ok',
        usage: { promptTokens: 5, completionTokens: 2 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.generateText({
        model: createMockModel('gpt-4o'),
        prompt: 'Hello',
      });

      expect(warnSpy).toHaveBeenCalledWith(
        '[Zentinelle] approaching rate limit'
      );
      warnSpy.mockRestore();
    });

    it('should include tool info in context when tools are provided', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });
      mockGenerateText.mockResolvedValue({
        text: 'ok',
        usage: { promptTokens: 10, completionTokens: 5 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.generateText({
        model: createMockModel('gpt-4o'),
        prompt: 'Use tools',
        tools: { calc: {} as any, search: {} as any },
      });

      expect(mockEvaluate).toHaveBeenCalledWith('model_request', {
        userId: undefined,
        context: expect.objectContaining({
          hasTools: true,
          toolCount: 2,
        }),
      });
    });
  });

  describe('streamText', () => {
    it('should evaluate policy before streaming', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });

      const mockStream = { pipe: vi.fn() };
      mockStreamText.mockReturnValue(mockStream);

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.streamText({
        model: createMockModel('claude-3-opus'),
        prompt: 'Stream this',
        userId: 'user-42',
      });

      expect(mockEvaluate).toHaveBeenCalledWith('model_request', {
        userId: 'user-42',
        context: expect.objectContaining({
          model: 'claude-3-opus',
          provider: 'anthropic',
          operation: 'streamText',
          streaming: true,
        }),
      });
    });

    it('should throw PolicyViolationError when stream is blocked', async () => {
      mockEvaluate.mockResolvedValue({
        allowed: false,
        reason: 'Streaming not permitted',
        warnings: [],
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await expect(
        governed.streamText({
          model: createMockModel('gpt-4o'),
          prompt: 'Stream this',
        })
      ).rejects.toThrow(PolicyViolationError);
    });

    it('should emit stream_start event after policy passes', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });
      mockStreamText.mockReturnValue({ pipe: vi.fn() });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.streamText({
        model: createMockModel('gpt-4o'),
        prompt: 'Hello',
        userId: 'user-42',
      });

      expect(mockEmit).toHaveBeenCalledWith(
        'stream_start',
        { model: 'gpt-4o', provider: 'openai' },
        { category: 'telemetry', userId: 'user-42' }
      );
    });
  });

  describe('generateObject', () => {
    it('should evaluate policy before generating object', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });
      mockGenerateObject.mockResolvedValue({
        object: { name: 'test' },
        usage: { promptTokens: 20, completionTokens: 10 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.generateObject({
        model: createMockModel('gpt-4o'),
        prompt: 'Generate an object',
        schema: { type: 'object' } as any,
        userId: 'user-42',
      });

      expect(mockEvaluate).toHaveBeenCalledWith('model_request', {
        userId: 'user-42',
        context: expect.objectContaining({
          model: 'gpt-4o',
          operation: 'generateObject',
          structured: true,
        }),
      });
    });

    it('should throw PolicyViolationError when object generation is blocked', async () => {
      mockEvaluate.mockResolvedValue({
        allowed: false,
        reason: 'Structured output not allowed',
        warnings: [],
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await expect(
        governed.generateObject({
          model: createMockModel('gpt-4o'),
          prompt: 'Generate',
          schema: {} as any,
        })
      ).rejects.toThrow(PolicyViolationError);
    });

    it('should track usage after generating object', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });
      mockGenerateObject.mockResolvedValue({
        object: { result: 'data' },
        usage: { promptTokens: 50, completionTokens: 30 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
        trackUsage: true,
      });

      await governed.generateObject({
        model: createMockModel('gpt-4o'),
        prompt: 'Generate',
        schema: {} as any,
      });

      expect(mockTrackUsage).toHaveBeenCalledWith({
        provider: 'openai',
        model: 'gpt-4o',
        inputTokens: 50,
        outputTokens: 30,
      });
    });
  });

  describe('tool (inline)', () => {
    it('should create a governed tool', () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      const calc = governed.tool({
        name: 'calculator',
        description: 'Calculate math',
        parameters: {} as any,
        execute: async () => 42,
      });

      expect(calc.description).toBe('Calculate math');
    });

    it('should evaluate policy on tool execution', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      const calc = governed.tool({
        name: 'calculator',
        description: 'Calculate',
        parameters: {} as any,
        execute: async () => 42,
      });

      await calc.execute!({});

      expect(mockEvaluate).toHaveBeenCalledWith('tool_call', {
        context: expect.objectContaining({ tool: 'calculator' }),
      });
    });

    it('should throw when tool policy blocks', async () => {
      mockEvaluate.mockResolvedValue({
        allowed: false,
        reason: 'Tool restricted',
        warnings: [],
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      const dangerousTool = governed.tool({
        name: 'shell_exec',
        description: 'Execute shell commands',
        parameters: {} as any,
        execute: async () => 'output',
        riskLevel: 'high',
      });

      await expect(dangerousTool.execute!({})).rejects.toThrow(
        PolicyViolationError
      );
    });

    it('should emit tool_call after successful execution', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      const tool = governed.tool({
        name: 'search',
        description: 'Search',
        parameters: {} as any,
        execute: async () => 'results',
      });

      await tool.execute!({});

      expect(mockEmitToolCall).toHaveBeenCalledWith({
        toolName: 'search',
        inputs: expect.any(Object),
        outputs: expect.any(Object),
        durationMs: expect.any(Number),
      });
    });
  });

  describe('register', () => {
    it('should delegate to client register', async () => {
      mockRegister.mockResolvedValue({
        agentId: 'agent-123',
        config: {},
        policies: [],
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.register(['chat', 'tools'], { version: '1.0' });

      expect(mockRegister).toHaveBeenCalledWith({
        capabilities: ['chat', 'tools'],
        metadata: { version: '1.0' },
      });
    });

    it('should use default capabilities when none provided', async () => {
      mockRegister.mockResolvedValue({
        agentId: 'agent-123',
        config: {},
        policies: [],
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.register();

      expect(mockRegister).toHaveBeenCalledWith({
        capabilities: ['chat', 'tools', 'streaming'],
        metadata: undefined,
      });
    });
  });

  describe('shutdown', () => {
    it('should delegate to client shutdown', async () => {
      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.shutdown();

      expect(mockShutdown).toHaveBeenCalled();
    });
  });

  describe('provider detection', () => {
    it('should detect openai from model name', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });
      mockGenerateText.mockResolvedValue({
        text: 'ok',
        usage: { promptTokens: 5, completionTokens: 2 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.generateText({
        model: createMockModel('gpt-4-turbo'),
        prompt: 'Hello',
      });

      expect(mockEvaluate).toHaveBeenCalledWith(
        'model_request',
        expect.objectContaining({
          context: expect.objectContaining({ provider: 'openai' }),
        })
      );
    });

    it('should detect anthropic from model name', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });
      mockGenerateText.mockResolvedValue({
        text: 'ok',
        usage: { promptTokens: 5, completionTokens: 2 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.generateText({
        model: createMockModel('claude-3-5-sonnet'),
        prompt: 'Hello',
      });

      expect(mockEvaluate).toHaveBeenCalledWith(
        'model_request',
        expect.objectContaining({
          context: expect.objectContaining({ provider: 'anthropic' }),
        })
      );
    });

    it('should detect google from model name', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });
      mockGenerateText.mockResolvedValue({
        text: 'ok',
        usage: { promptTokens: 5, completionTokens: 2 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.generateText({
        model: createMockModel('gemini-pro'),
        prompt: 'Hello',
      });

      expect(mockEvaluate).toHaveBeenCalledWith(
        'model_request',
        expect.objectContaining({
          context: expect.objectContaining({ provider: 'google' }),
        })
      );
    });

    it('should return unknown for unrecognized models', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });
      mockGenerateText.mockResolvedValue({
        text: 'ok',
        usage: { promptTokens: 5, completionTokens: 2 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      await governed.generateText({
        model: createMockModel('custom-model-v3'),
        prompt: 'Hello',
      });

      expect(mockEvaluate).toHaveBeenCalledWith(
        'model_request',
        expect.objectContaining({
          context: expect.objectContaining({ provider: 'unknown' }),
        })
      );
    });

    it('should handle model without modelId', async () => {
      mockEvaluate.mockResolvedValue({ allowed: true, warnings: [] });
      mockGenerateText.mockResolvedValue({
        text: 'ok',
        usage: { promptTokens: 5, completionTokens: 2 },
      });

      const governed = createGovernedAI({
        apiKey: 'sk_agent_test_key_123',
      });

      // Model without modelId property
      await governed.generateText({
        model: { provider: 'test' } as any,
        prompt: 'Hello',
      });

      expect(mockEvaluate).toHaveBeenCalledWith(
        'model_request',
        expect.objectContaining({
          context: expect.objectContaining({ model: 'unknown' }),
        })
      );
    });
  });
});
