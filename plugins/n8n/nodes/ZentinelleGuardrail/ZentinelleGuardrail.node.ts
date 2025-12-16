import {
	IExecuteFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	NodeOperationError,
} from 'n8n-workflow';

export class ZentinelleGuardrail implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Zentinelle Guardrail',
		name: 'zentinelleGuardrail',
		icon: 'file:zentinelle.svg',
		group: ['transform'],
		version: 1,
		subtitle: 'Policy enforcement gate',
		description: 'Enforce governance policies - blocks workflow if policy denies',
		defaults: {
			name: 'Guardrail',
		},
		inputs: ['main'],
		outputs: ['main', 'main'],
		outputNames: ['Allowed', 'Blocked'],
		credentials: [
			{
				name: 'zentinelleApi',
				required: true,
			},
		],
		properties: [
			{
				displayName: 'Action',
				name: 'action',
				type: 'string',
				default: 'workflow_step',
				required: true,
				description: 'Action to evaluate (e.g., ai_request, tool_call, data_access)',
			},
			{
				displayName: 'User ID Field',
				name: 'userIdField',
				type: 'string',
				default: 'userId',
				description: 'Field name in input data containing user ID',
			},
			{
				displayName: 'Include Input as Context',
				name: 'includeInputContext',
				type: 'boolean',
				default: true,
				description: 'Include input data in policy evaluation context',
			},
			{
				displayName: 'Additional Context',
				name: 'additionalContext',
				type: 'json',
				default: '{}',
				description: 'Extra context for policy evaluation',
			},
			{
				displayName: 'On Block Behavior',
				name: 'onBlockBehavior',
				type: 'options',
				options: [
					{
						name: 'Route to Blocked Output',
						value: 'route',
						description: 'Send to second output for handling',
					},
					{
						name: 'Stop Workflow',
						value: 'stop',
						description: 'Stop the workflow execution',
					},
					{
						name: 'Continue with Warning',
						value: 'warn',
						description: 'Log warning but continue execution',
					},
				],
				default: 'route',
				description: 'What to do when policy blocks the action',
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const allowedItems: INodeExecutionData[] = [];
		const blockedItems: INodeExecutionData[] = [];

		const credentials = await this.getCredentials('zentinelleApi');
		const endpoint = credentials.endpoint as string;
		const apiKey = credentials.apiKey as string;

		const action = this.getNodeParameter('action', 0) as string;
		const userIdField = this.getNodeParameter('userIdField', 0) as string;
		const includeInputContext = this.getNodeParameter('includeInputContext', 0) as boolean;
		const additionalContextJson = this.getNodeParameter('additionalContext', 0, '{}') as string;
		const onBlockBehavior = this.getNodeParameter('onBlockBehavior', 0) as string;

		for (let i = 0; i < items.length; i++) {
			const item = items[i];

			try {
				// Extract user ID from input
				const userId = item.json[userIdField] as string || '';

				// Build context
				let context: Record<string, unknown>;
				try {
					context = JSON.parse(additionalContextJson);
				} catch {
					throw new Error(`Invalid JSON in additionalContext field: ${additionalContextJson.slice(0, 100)}`);
				}
				if (includeInputContext) {
					// Sanitize input for context (truncate large values)
					const sanitizedInput: Record<string, unknown> = {};
					for (const [key, value] of Object.entries(item.json)) {
						if (typeof value === 'string' && value.length > 500) {
							sanitizedInput[key] = value.substring(0, 500) + '...';
						} else {
							sanitizedInput[key] = value;
						}
					}
					context = { ...context, input: sanitizedInput };
				}

				// Evaluate policy
				const response = await this.helpers.httpRequest({
					method: 'POST',
					url: `${endpoint}/api/v1/evaluate`,
					headers: {
						'X-Zentinelle-Key': apiKey,
						'Content-Type': 'application/json',
					},
					body: {
						action,
						user_id: userId,
						context,
					},
				});

				// Add governance metadata to output
				const outputItem: INodeExecutionData = {
					json: {
						...item.json,
						_zentinelle: {
							allowed: response.allowed,
							reason: response.reason,
							warnings: response.warnings || [],
							policiesEvaluated: response.policies_evaluated || [],
						},
					},
					pairedItem: { item: i },
				};

				if (response.allowed) {
					allowedItems.push(outputItem);
				} else {
					// Handle blocked items based on behavior setting
					if (onBlockBehavior === 'stop') {
						throw new NodeOperationError(
							this.getNode(),
							`Policy blocked: ${response.reason || 'Action not allowed'}`,
							{ itemIndex: i }
						);
					} else if (onBlockBehavior === 'warn') {
						console.warn(`Zentinelle policy warning: ${response.reason}`);
						allowedItems.push(outputItem);
					} else {
						// Route to blocked output
						blockedItems.push(outputItem);
					}
				}

			} catch (error) {
				if (error instanceof NodeOperationError) {
					throw error;
				}

				if (this.continueOnFail()) {
					const errorMessage = error instanceof Error ? error.message : String(error);
					blockedItems.push({
						json: {
							...item.json,
							_zentinelle: {
								allowed: false,
								error: errorMessage,
							},
						},
						pairedItem: { item: i },
					});
					continue;
				}
				throw new NodeOperationError(this.getNode(), error as Error, { itemIndex: i });
			}
		}

		return [allowedItems, blockedItems];
	}
}
