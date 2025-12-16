/**
 * Governed tool wrapper for Vercel AI SDK.
 */

import type { CoreTool } from 'ai';
import { ZentinelleClient } from 'zentinelle';
import { PolicyViolationError } from './errors';

export interface GovernedToolOptions<TParams, TResult> {
  /** Zentinelle client instance */
  client: ZentinelleClient;
  /** Tool name for policy evaluation */
  name: string;
  /** Tool description */
  description: string;
  /** Zod schema for parameters */
  parameters: TParams;
  /** Tool execution function */
  execute: (params: TParams extends { parse: (x: unknown) => infer R } ? R : TParams) => Promise<TResult>;
  /** Risk level for policy evaluation */
  riskLevel?: 'low' | 'medium' | 'high';
  /** Whether to fail silently on policy block */
  failSilent?: boolean;
  /** Message to return when blocked (if failSilent) */
  blockMessage?: string;
}

/**
 * Create a governed tool with Zentinelle policy enforcement.
 *
 * @example
 * ```typescript
 * import { z } from 'zod';
 * import { governedTool } from 'zentinelle-ai';
 * import { ZentinelleClient } from 'zentinelle';
 *
 * const client = new ZentinelleClient({ apiKey: '...', agentType: 'vercel-ai' });
 *
 * const calculator = governedTool({
 *   client,
 *   name: 'calculator',
 *   description: 'Perform calculations',
 *   parameters: z.object({
 *     expression: z.string().describe('Math expression'),
 *   }),
 *   execute: async ({ expression }) => {
 *     return calculateSafely(expression); // Use a safe math parser, never eval()
 *   },
 *   riskLevel: 'low',
 * });
 *
 * // Use with generateText
 * const { text } = await generateText({
 *   model: openai('gpt-4o'),
 *   tools: { calculator },
 *   prompt: 'What is 2 + 2?',
 * });
 * ```
 */
export function governedTool<TParams, TResult>(
  options: GovernedToolOptions<TParams, TResult>
): CoreTool<TParams, TResult> {
  const {
    client,
    name,
    description,
    parameters,
    execute,
    riskLevel = 'low',
    failSilent = false,
    blockMessage = 'Tool execution blocked by policy',
  } = options;

  const governedExecute = async (
    params: TParams extends { parse: (x: unknown) => infer R } ? R : TParams
  ): Promise<TResult> => {
    const startTime = Date.now();

    // Evaluate policy
    const result = await client.evaluate('tool_call', {
      context: {
        tool: name,
        riskLevel,
        params: sanitizeParams(params),
      },
    });

    if (!result.allowed) {
      if (failSilent) {
        return blockMessage as unknown as TResult;
      }
      throw new PolicyViolationError(
        result.reason ?? `Tool '${name}' blocked by policy`,
        { allowed: false, reason: result.reason, warnings: result.warnings }
      );
    }

    // Log warnings
    for (const warning of result.warnings) {
      console.warn(`[Zentinelle] Tool ${name}: ${warning}`);
    }

    try {
      // Execute the tool
      const output = await execute(params);
      const durationMs = Date.now() - startTime;

      // Track successful execution
      client.emitToolCall({
        toolName: name,
        inputs: sanitizeParams(params),
        outputs: { result: sanitizeOutput(output) },
        durationMs,
      });

      return output;

    } catch (error) {
      const durationMs = Date.now() - startTime;

      // Track error
      client.emit('tool_error', {
        tool: name,
        error_type: (error as Error).name,
        error_message: (error as Error).message?.slice(0, 500),
        duration_ms: durationMs,
      }, { category: 'alert' });

      throw error;
    }
  };

  return {
    description,
    parameters,
    execute: governedExecute,
  } as CoreTool<TParams, TResult>;
}

/**
 * Create multiple governed tools at once.
 */
export function governedTools<T extends Record<string, GovernedToolOptions<unknown, unknown>>>(
  client: ZentinelleClient,
  tools: T
): { [K in keyof T]: CoreTool } {
  const result = {} as { [K in keyof T]: CoreTool };

  for (const [key, config] of Object.entries(tools)) {
    result[key as keyof T] = governedTool({
      client,
      ...config,
    });
  }

  return result;
}

// Helper functions
function sanitizeParams(params: unknown): Record<string, unknown> {
  if (typeof params !== 'object' || params === null) {
    return { value: String(params).slice(0, 500) };
  }

  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(params)) {
    if (typeof value === 'string') {
      result[key] = value.slice(0, 200);
    } else if (typeof value === 'object') {
      result[key] = '[object]';
    } else {
      result[key] = value;
    }
  }
  return result;
}

function sanitizeOutput(output: unknown): string {
  if (typeof output === 'string') {
    return output.slice(0, 500);
  }
  try {
    return JSON.stringify(output).slice(0, 500);
  } catch {
    return '[non-serializable]';
  }
}
