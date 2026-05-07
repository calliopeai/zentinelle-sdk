import { describe, it, expect, vi, beforeEach } from 'vitest';
import { governedTool, governedTools } from '../src/tool';
import { PolicyViolationError } from '../src/errors';

// Mock the zentinelle module
vi.mock('zentinelle', () => ({
  ZentinelleClient: vi.fn(),
}));

function createMockClient() {
  return {
    evaluate: vi.fn(),
    emit: vi.fn(),
    emitToolCall: vi.fn(),
    emitModelRequest: vi.fn(),
    shutdown: vi.fn().mockResolvedValue(undefined),
  };
}

describe('governedTool', () => {
  let mockClient: ReturnType<typeof createMockClient>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockClient = createMockClient();
  });

  it('should create a tool with description and parameters', () => {
    mockClient.evaluate.mockResolvedValue({ allowed: true, warnings: [] });

    const tool = governedTool({
      client: mockClient as any,
      name: 'calculator',
      description: 'Perform calculations',
      parameters: { type: 'object' } as any,
      execute: async () => 42,
    });

    expect(tool.description).toBe('Perform calculations');
    expect(tool.parameters).toEqual({ type: 'object' });
    expect(tool.execute).toBeDefined();
  });

  it('should evaluate policy before executing the tool', async () => {
    mockClient.evaluate.mockResolvedValue({ allowed: true, warnings: [] });
    const executeFn = vi.fn().mockResolvedValue('result');

    const tool = governedTool({
      client: mockClient as any,
      name: 'web_search',
      description: 'Search the web',
      parameters: {} as any,
      execute: executeFn,
    });

    await tool.execute!({ query: 'test' });

    expect(mockClient.evaluate).toHaveBeenCalledWith('tool_call', {
      context: expect.objectContaining({
        tool: 'web_search',
        riskLevel: 'low',
      }),
    });
    expect(executeFn).toHaveBeenCalledWith({ query: 'test' });
  });

  it('should throw PolicyViolationError when policy blocks', async () => {
    mockClient.evaluate.mockResolvedValue({
      allowed: false,
      reason: 'Tool not permitted for this agent',
      warnings: ['policy: tool_restriction'],
    });

    const tool = governedTool({
      client: mockClient as any,
      name: 'file_write',
      description: 'Write files',
      parameters: {} as any,
      execute: async () => 'done',
    });

    await expect(tool.execute!({ path: '/etc/passwd' })).rejects.toThrow(
      PolicyViolationError
    );
    await expect(tool.execute!({ path: '/etc/passwd' })).rejects.toThrow(
      'Tool not permitted for this agent'
    );
  });

  it('should not execute the tool when policy blocks', async () => {
    mockClient.evaluate.mockResolvedValue({
      allowed: false,
      reason: 'blocked',
      warnings: [],
    });
    const executeFn = vi.fn().mockResolvedValue('result');

    const tool = governedTool({
      client: mockClient as any,
      name: 'dangerous_tool',
      description: 'A dangerous tool',
      parameters: {} as any,
      execute: executeFn,
    });

    await expect(tool.execute!({})).rejects.toThrow(PolicyViolationError);
    expect(executeFn).not.toHaveBeenCalled();
  });

  it('should return blockMessage when failSilent is true and blocked', async () => {
    mockClient.evaluate.mockResolvedValue({
      allowed: false,
      reason: 'not allowed',
      warnings: [],
    });

    const tool = governedTool({
      client: mockClient as any,
      name: 'risky_tool',
      description: 'Risky',
      parameters: {} as any,
      execute: async () => 'result',
      failSilent: true,
      blockMessage: 'This action is not available',
    });

    const result = await tool.execute!({});
    expect(result).toBe('This action is not available');
  });

  it('should use default blockMessage when failSilent and no custom message', async () => {
    mockClient.evaluate.mockResolvedValue({
      allowed: false,
      reason: 'blocked',
      warnings: [],
    });

    const tool = governedTool({
      client: mockClient as any,
      name: 'blocked_tool',
      description: 'Blocked',
      parameters: {} as any,
      execute: async () => 'result',
      failSilent: true,
    });

    const result = await tool.execute!({});
    expect(result).toBe('Tool execution blocked by policy');
  });

  it('should emit tool_call event after successful execution', async () => {
    mockClient.evaluate.mockResolvedValue({ allowed: true, warnings: [] });

    const tool = governedTool({
      client: mockClient as any,
      name: 'calculator',
      description: 'Calculate',
      parameters: {} as any,
      execute: async (params: any) => params.a + params.b,
    });

    await tool.execute!({ a: 2, b: 3 });

    expect(mockClient.emitToolCall).toHaveBeenCalledWith({
      toolName: 'calculator',
      inputs: expect.any(Object),
      outputs: expect.objectContaining({ result: expect.any(String) }),
      durationMs: expect.any(Number),
    });
  });

  it('should emit tool_error event when execution throws', async () => {
    mockClient.evaluate.mockResolvedValue({ allowed: true, warnings: [] });

    const tool = governedTool({
      client: mockClient as any,
      name: 'failing_tool',
      description: 'Fails',
      parameters: {} as any,
      execute: async () => {
        throw new Error('execution failed');
      },
    });

    await expect(tool.execute!({})).rejects.toThrow('execution failed');

    expect(mockClient.emit).toHaveBeenCalledWith(
      'tool_error',
      expect.objectContaining({
        tool: 'failing_tool',
        error_type: 'Error',
        error_message: 'execution failed',
        duration_ms: expect.any(Number),
      }),
      { category: 'alert' }
    );
  });

  it('should pass risk level through to policy evaluation', async () => {
    mockClient.evaluate.mockResolvedValue({ allowed: true, warnings: [] });

    const tool = governedTool({
      client: mockClient as any,
      name: 'dangerous_action',
      description: 'High risk action',
      parameters: {} as any,
      execute: async () => 'done',
      riskLevel: 'high',
    });

    await tool.execute!({});

    expect(mockClient.evaluate).toHaveBeenCalledWith('tool_call', {
      context: expect.objectContaining({ riskLevel: 'high' }),
    });
  });

  it('should default risk level to low', async () => {
    mockClient.evaluate.mockResolvedValue({ allowed: true, warnings: [] });

    const tool = governedTool({
      client: mockClient as any,
      name: 'safe_tool',
      description: 'Safe tool',
      parameters: {} as any,
      execute: async () => 'done',
    });

    await tool.execute!({});

    expect(mockClient.evaluate).toHaveBeenCalledWith('tool_call', {
      context: expect.objectContaining({ riskLevel: 'low' }),
    });
  });

  it('should log warnings from policy evaluation', async () => {
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
    mockClient.evaluate.mockResolvedValue({
      allowed: true,
      warnings: ['approaching tool call limit', 'audit required'],
    });

    const tool = governedTool({
      client: mockClient as any,
      name: 'monitored_tool',
      description: 'Monitored',
      parameters: {} as any,
      execute: async () => 'done',
    });

    await tool.execute!({});

    expect(warnSpy).toHaveBeenCalledWith(
      '[Zentinelle] Tool monitored_tool: approaching tool call limit'
    );
    expect(warnSpy).toHaveBeenCalledWith(
      '[Zentinelle] Tool monitored_tool: audit required'
    );
    warnSpy.mockRestore();
  });

  it('should sanitize params by truncating long strings', async () => {
    mockClient.evaluate.mockResolvedValue({ allowed: true, warnings: [] });

    const tool = governedTool({
      client: mockClient as any,
      name: 'text_tool',
      description: 'Text processing',
      parameters: {} as any,
      execute: async () => 'done',
    });

    const longString = 'a'.repeat(500);
    await tool.execute!({ text: longString });

    // The params passed to evaluate should be sanitized
    const evaluateCall = mockClient.evaluate.mock.calls[0];
    const params = evaluateCall[1].context.params;
    // sanitizeParams truncates strings to 200 chars
    expect(params.text.length).toBeLessThanOrEqual(200);
  });

  it('should sanitize non-object params', async () => {
    mockClient.evaluate.mockResolvedValue({ allowed: true, warnings: [] });

    const tool = governedTool({
      client: mockClient as any,
      name: 'simple_tool',
      description: 'Simple',
      parameters: {} as any,
      execute: async () => 'done',
    });

    // Passing a string directly (unusual but should be handled)
    await tool.execute!('just-a-string' as any);

    const evaluateCall = mockClient.evaluate.mock.calls[0];
    const params = evaluateCall[1].context.params;
    expect(params.value).toBe('just-a-string');
  });

  it('should include the PolicyViolationError result when blocked', async () => {
    mockClient.evaluate.mockResolvedValue({
      allowed: false,
      reason: 'Rate limit exceeded',
      warnings: ['limit approaching'],
    });

    const tool = governedTool({
      client: mockClient as any,
      name: 'rate_limited',
      description: 'Rate limited tool',
      parameters: {} as any,
      execute: async () => 'done',
    });

    try {
      await tool.execute!({});
      expect.fail('should have thrown');
    } catch (error) {
      expect(error).toBeInstanceOf(PolicyViolationError);
      const pve = error as PolicyViolationError;
      expect(pve.result.allowed).toBe(false);
      expect(pve.result.reason).toBe('Rate limit exceeded');
      expect(pve.result.warnings).toEqual(['limit approaching']);
    }
  });
});

describe('governedTools', () => {
  let mockClient: ReturnType<typeof createMockClient>;

  beforeEach(() => {
    vi.clearAllMocks();
    mockClient = createMockClient();
    mockClient.evaluate.mockResolvedValue({ allowed: true, warnings: [] });
  });

  it('should create multiple governed tools at once', () => {
    const tools = governedTools(mockClient as any, {
      calculator: {
        name: 'calculator',
        description: 'Calculate',
        parameters: {} as any,
        execute: async () => 42,
      } as any,
      search: {
        name: 'search',
        description: 'Search',
        parameters: {} as any,
        execute: async () => 'results',
      } as any,
    });

    expect(tools.calculator).toBeDefined();
    expect(tools.calculator.description).toBe('Calculate');
    expect(tools.search).toBeDefined();
    expect(tools.search.description).toBe('Search');
  });

  it('should inject the client into each tool', async () => {
    const tools = governedTools(mockClient as any, {
      tool1: {
        name: 'tool1',
        description: 'Tool 1',
        parameters: {} as any,
        execute: async () => 'result1',
      } as any,
    });

    await tools.tool1.execute!({});

    // The client's evaluate should have been called by the governed tool
    expect(mockClient.evaluate).toHaveBeenCalledWith('tool_call', expect.anything());
  });
});
