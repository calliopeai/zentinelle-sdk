import {
	IExecuteFunctions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	NodeOperationError,
} from 'n8n-workflow';

export class Zentinelle implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Zentinelle',
		name: 'zentinelle',
		icon: 'file:zentinelle.svg',
		group: ['transform'],
		version: 1,
		subtitle: '={{$parameter["operation"]}}',
		description: 'AI Agent Governance - Policy Evaluation & Telemetry',
		defaults: {
			name: 'Zentinelle',
		},
		inputs: ['main'],
		outputs: ['main'],
		credentials: [
			{
				name: 'zentinelleApi',
				required: true,
			},
		],
		properties: [
			{
				displayName: 'Operation',
				name: 'operation',
				type: 'options',
				noDataExpression: true,
				options: [
					{
						name: 'Evaluate Policy',
						value: 'evaluate',
						description: 'Evaluate an action against governance policies',
						action: 'Evaluate policy',
					},
					{
						name: 'Emit Event',
						value: 'emit',
						description: 'Send a telemetry or audit event',
						action: 'Emit event',
					},
					{
						name: 'Get Config',
						value: 'getConfig',
						description: 'Get agent configuration and policies',
						action: 'Get config',
					},
					{
						name: 'Get Secrets',
						value: 'getSecrets',
						description: 'Retrieve secrets for the agent',
						action: 'Get secrets',
					},
				],
				default: 'evaluate',
			},
			// Evaluate operation fields
			{
				displayName: 'Action',
				name: 'action',
				type: 'string',
				default: 'workflow_step',
				required: true,
				displayOptions: {
					show: {
						operation: ['evaluate'],
					},
				},
				description: 'The action to evaluate (e.g., tool_call, model_request)',
			},
			{
				displayName: 'User ID',
				name: 'userId',
				type: 'string',
				default: '',
				displayOptions: {
					show: {
						operation: ['evaluate', 'emit'],
					},
				},
				description: 'User identifier for the action',
			},
			{
				displayName: 'Context',
				name: 'context',
				type: 'json',
				default: '{}',
				displayOptions: {
					show: {
						operation: ['evaluate'],
					},
				},
				description: 'Additional context for policy evaluation',
			},
			// Emit operation fields
			{
				displayName: 'Event Type',
				name: 'eventType',
				type: 'string',
				default: 'workflow_event',
				required: true,
				displayOptions: {
					show: {
						operation: ['emit'],
					},
				},
				description: 'Type of event to emit',
			},
			{
				displayName: 'Category',
				name: 'category',
				type: 'options',
				options: [
					{ name: 'Telemetry', value: 'telemetry' },
					{ name: 'Audit', value: 'audit' },
					{ name: 'Alert', value: 'alert' },
					{ name: 'Compliance', value: 'compliance' },
				],
				default: 'telemetry',
				displayOptions: {
					show: {
						operation: ['emit'],
					},
				},
				description: 'Event category',
			},
			{
				displayName: 'Payload',
				name: 'payload',
				type: 'json',
				default: '{}',
				displayOptions: {
					show: {
						operation: ['emit'],
					},
				},
				description: 'Event payload data',
			},
			// Get Config/Secrets fields
			{
				displayName: 'Agent ID',
				name: 'agentId',
				type: 'string',
				default: '',
				required: true,
				displayOptions: {
					show: {
						operation: ['getConfig', 'getSecrets'],
					},
				},
				description: 'Agent identifier',
			},
		],
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const returnData: INodeExecutionData[] = [];
		const credentials = await this.getCredentials('zentinelleApi');
		const operation = this.getNodeParameter('operation', 0) as string;

		const endpoint = credentials.endpoint as string;
		const apiKey = credentials.apiKey as string;

		for (let i = 0; i < items.length; i++) {
			try {
				let responseData;

				if (operation === 'evaluate') {
					const action = this.getNodeParameter('action', i) as string;
					const userId = this.getNodeParameter('userId', i, '') as string;
					const contextJson = this.getNodeParameter('context', i, '{}') as string;
					let context: Record<string, unknown>;
					try {
						context = JSON.parse(contextJson);
					} catch {
						throw new Error(`Invalid JSON in context field: ${contextJson.slice(0, 100)}`);
					}

					responseData = await this.helpers.httpRequest({
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

					// Add workflow branching based on allowed status
					responseData = {
						...responseData,
						_zentinelle: {
							allowed: responseData.allowed,
							reason: responseData.reason,
							shouldContinue: responseData.allowed,
						},
					};

				} else if (operation === 'emit') {
					const eventType = this.getNodeParameter('eventType', i) as string;
					const category = this.getNodeParameter('category', i) as string;
					const userId = this.getNodeParameter('userId', i, '') as string;
					const payloadJson = this.getNodeParameter('payload', i, '{}') as string;
					let payload: Record<string, unknown>;
					try {
						payload = JSON.parse(payloadJson);
					} catch {
						throw new Error(`Invalid JSON in payload field: ${payloadJson.slice(0, 100)}`);
					}

					responseData = await this.helpers.httpRequest({
						method: 'POST',
						url: `${endpoint}/api/v1/events`,
						headers: {
							'X-Zentinelle-Key': apiKey,
							'Content-Type': 'application/json',
						},
						body: {
							events: [{
								type: eventType,
								category,
								user_id: userId,
								payload,
								timestamp: new Date().toISOString(),
							}],
						},
					});

				} else if (operation === 'getConfig') {
					const agentId = this.getNodeParameter('agentId', i) as string;

					responseData = await this.helpers.httpRequest({
						method: 'GET',
						url: `${endpoint}/api/v1/agents/${agentId}/config`,
						headers: {
							'X-Zentinelle-Key': apiKey,
						},
					});

				} else if (operation === 'getSecrets') {
					const agentId = this.getNodeParameter('agentId', i) as string;

					responseData = await this.helpers.httpRequest({
						method: 'GET',
						url: `${endpoint}/api/v1/agents/${agentId}/secrets`,
						headers: {
							'X-Zentinelle-Key': apiKey,
						},
					});
				}

				returnData.push({
					json: responseData,
					pairedItem: { item: i },
				});

			} catch (error) {
				if (this.continueOnFail()) {
					const errorMessage = error instanceof Error ? error.message : String(error);
					returnData.push({
						json: {
							error: errorMessage,
							_zentinelle: { allowed: false, shouldContinue: false },
						},
						pairedItem: { item: i },
					});
					continue;
				}
				throw new NodeOperationError(this.getNode(), error as Error, { itemIndex: i });
			}
		}

		return [returnData];
	}
}
