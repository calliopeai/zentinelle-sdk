/**
 * Governed AI - Wrapper for Vercel AI SDK with Zentinelle governance.
 */

import type {
  generateText as generateTextFn,
  streamText as streamTextFn,
  generateObject as generateObjectFn,
  streamObject as streamObjectFn,
  CoreTool,
  LanguageModel,
} from 'ai';
import { ZentinelleClient } from 'zentinelle';
import { PolicyViolationError } from './errors';

export interface GovernedAIOptions {
  apiKey: string;
  agentType?: string;
  endpoint?: string;
  failOpen?: boolean;
  trackUsage?: boolean;
  evaluateInput?: boolean;
  evaluateOutput?: boolean;
}

interface GenerateTextOptions {
  model: LanguageModel;
  prompt?: string;
  messages?: Array<{ role: string; content: string }>;
  system?: string;
  tools?: Record<string, CoreTool>;
  userId?: string;
  [key: string]: unknown;
}

interface StreamTextOptions extends GenerateTextOptions {}

interface GenerateObjectOptions {
  model: LanguageModel;
  prompt?: string;
  schema: unknown;
  userId?: string;
  [key: string]: unknown;
}

type GenerateTextResult = Awaited<ReturnType<typeof generateTextFn>>;
type StreamTextResult = Awaited<ReturnType<typeof streamTextFn>>;
type GenerateObjectResult = Awaited<ReturnType<typeof generateObjectFn>>;
type StreamObjectResult = Awaited<ReturnType<typeof streamObjectFn>>;

export function createGovernedAI(options: GovernedAIOptions) {
  const client = new ZentinelleClient({
    apiKey: options.apiKey,
    agentType: options.agentType ?? 'vercel-ai',
    endpoint: options.endpoint,
    failOpen: options.failOpen ?? false,
  });

  const trackUsage = options.trackUsage ?? true;
  const evaluateInput = options.evaluateInput ?? true;
  const evaluateOutput = options.evaluateOutput ?? false;

  /**
   * Governed generateText - evaluate policies before and track usage after.
   */
  async function generateText(
    generateTextFn: typeof import('ai').generateText,
    opts: GenerateTextOptions
  ): Promise<GenerateTextResult> {
    const { userId, ...aiOptions } = opts;
    const modelId = getModelId(opts.model);
    const startTime = Date.now();

    // Pre-execution policy check
    if (evaluateInput) {
      const result = await client.evaluate('model_request', {
        userId,
        context: {
          model: modelId,
          provider: getProvider(modelId),
          operation: 'generateText',
          hasTools: !!opts.tools,
          toolCount: opts.tools ? Object.keys(opts.tools).length : 0,
        },
      });

      if (!result.allowed) {
        throw new PolicyViolationError(
          result.reason ?? 'Request blocked by policy',
          { allowed: false, reason: result.reason, warnings: result.warnings }
        );
      }

      // Log warnings
      for (const warning of result.warnings) {
        console.warn(`[Zentinelle] ${warning}`);
      }
    }

    // Execute
    const response = await generateTextFn(aiOptions as Parameters<typeof generateTextFn>[0]);

    // Track usage
    const durationMs = Date.now() - startTime;
    if (trackUsage && response.usage) {
      client.trackUsage({
        provider: getProvider(modelId),
        model: modelId,
        inputTokens: response.usage.promptTokens,
        outputTokens: response.usage.completionTokens,
      });

      client.emitModelRequest({
        provider: getProvider(modelId),
        model: modelId,
        inputTokens: response.usage.promptTokens,
        outputTokens: response.usage.completionTokens,
        userId,
        durationMs,
      });
    }

    // Post-execution policy check (optional)
    if (evaluateOutput && response.text) {
      const result = await client.evaluate('model_response', {
        userId,
        context: {
          model: modelId,
          outputLength: response.text.length,
        },
      });

      if (!result.allowed) {
        throw new PolicyViolationError(
          result.reason ?? 'Response blocked by policy',
          { allowed: false, reason: result.reason, warnings: result.warnings }
        );
      }
    }

    return response;
  }

  /**
   * Governed streamText - evaluate policies before streaming.
   */
  async function streamText(
    streamTextFn: typeof import('ai').streamText,
    opts: StreamTextOptions
  ): Promise<StreamTextResult> {
    const { userId, ...aiOptions } = opts;
    const modelId = getModelId(opts.model);

    // Pre-execution policy check
    if (evaluateInput) {
      const result = await client.evaluate('model_request', {
        userId,
        context: {
          model: modelId,
          provider: getProvider(modelId),
          operation: 'streamText',
          streaming: true,
        },
      });

      if (!result.allowed) {
        throw new PolicyViolationError(
          result.reason ?? 'Request blocked by policy',
          { allowed: false, reason: result.reason, warnings: result.warnings }
        );
      }
    }

    // Execute stream
    const stream = streamTextFn(aiOptions as Parameters<typeof streamTextFn>[0]);

    // Emit start event
    client.emit('stream_start', {
      model: modelId,
      provider: getProvider(modelId),
    }, { category: 'telemetry', userId });

    return stream;
  }

  /**
   * Governed generateObject - evaluate policies for structured output.
   */
  async function generateObject<T>(
    generateObjectFn: typeof import('ai').generateObject,
    opts: GenerateObjectOptions
  ): Promise<GenerateObjectResult> {
    const { userId, ...aiOptions } = opts;
    const modelId = getModelId(opts.model);
    const startTime = Date.now();

    if (evaluateInput) {
      const result = await client.evaluate('model_request', {
        userId,
        context: {
          model: modelId,
          provider: getProvider(modelId),
          operation: 'generateObject',
          structured: true,
        },
      });

      if (!result.allowed) {
        throw new PolicyViolationError(
          result.reason ?? 'Request blocked by policy',
          { allowed: false, reason: result.reason, warnings: result.warnings }
        );
      }
    }

    const response = await generateObjectFn(aiOptions as Parameters<typeof generateObjectFn>[0]);

    const durationMs = Date.now() - startTime;
    if (trackUsage && response.usage) {
      client.trackUsage({
        provider: getProvider(modelId),
        model: modelId,
        inputTokens: response.usage.promptTokens,
        outputTokens: response.usage.completionTokens,
      });
    }

    return response;
  }

  /**
   * Create a governed tool with policy enforcement.
   */
  function tool<TParams, TResult>(config: {
    name: string;
    description: string;
    parameters: TParams;
    execute: (params: TParams extends { parse: (x: unknown) => infer R } ? R : TParams) => Promise<TResult>;
    riskLevel?: 'low' | 'medium' | 'high';
  }): CoreTool<TParams, TResult> {
    const originalExecute = config.execute;

    const governedExecute = async (params: TParams extends { parse: (x: unknown) => infer R } ? R : TParams) => {
      // Evaluate tool call policy
      const result = await client.evaluate('tool_call', {
        context: {
          tool: config.name,
          riskLevel: config.riskLevel ?? 'low',
          params: JSON.stringify(params).slice(0, 500),
        },
      });

      if (!result.allowed) {
        throw new PolicyViolationError(
          result.reason ?? `Tool '${config.name}' blocked by policy`,
          { allowed: false, reason: result.reason, warnings: result.warnings }
        );
      }

      const startTime = Date.now();
      const output = await originalExecute(params);
      const durationMs = Date.now() - startTime;

      // Track tool usage
      client.emitToolCall({
        toolName: config.name,
        inputs: params as Record<string, unknown>,
        outputs: { result: JSON.stringify(output).slice(0, 500) },
        durationMs,
      });

      return output;
    };

    return {
      description: config.description,
      parameters: config.parameters,
      execute: governedExecute,
    } as CoreTool<TParams, TResult>;
  }

  /**
   * Register the agent with Zentinelle.
   */
  async function register(capabilities?: string[], metadata?: Record<string, unknown>) {
    return client.register({
      capabilities: capabilities ?? ['chat', 'tools', 'streaming'],
      metadata,
    });
  }

  /**
   * Shutdown and flush events.
   */
  async function shutdown() {
    return client.shutdown();
  }

  return {
    client,
    generateText: (opts: GenerateTextOptions) =>
      import('ai').then((ai) => generateText(ai.generateText, opts)),
    streamText: (opts: StreamTextOptions) =>
      import('ai').then((ai) => streamText(ai.streamText, opts)),
    generateObject: (opts: GenerateObjectOptions) =>
      import('ai').then((ai) => generateObject(ai.generateObject, opts)),
    tool,
    register,
    shutdown,
  };
}

// Helper functions
function getModelId(model: LanguageModel): string {
  // Extract model ID from LanguageModel
  return (model as { modelId?: string }).modelId ?? 'unknown';
}

function getProvider(modelId: string): string {
  if (modelId.startsWith('gpt-') || modelId.includes('openai')) return 'openai';
  if (modelId.startsWith('claude-') || modelId.includes('anthropic')) return 'anthropic';
  if (modelId.startsWith('gemini-') || modelId.includes('google')) return 'google';
  if (modelId.startsWith('mistral')) return 'mistral';
  return 'unknown';
}
