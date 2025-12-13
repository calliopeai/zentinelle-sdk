import {
	IHookFunctions,
	IWebhookFunctions,
	INodeType,
	INodeTypeDescription,
	IWebhookResponseData,
} from 'n8n-workflow';

export class ZentinelleTrigger implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'Zentinelle Trigger',
		name: 'zentinelleTrigger',
		icon: 'file:zentinelle.svg',
		group: ['trigger'],
		version: 1,
		subtitle: '={{$parameter["event"]}}',
		description: 'Trigger workflow from Zentinelle events (webhooks)',
		defaults: {
			name: 'Zentinelle Trigger',
		},
		inputs: [],
		outputs: ['main'],
		credentials: [
			{
				name: 'zentinelleApi',
				required: true,
			},
		],
		webhooks: [
			{
				name: 'default',
				httpMethod: 'POST',
				responseMode: 'onReceived',
				path: 'zentinelle',
			},
		],
		properties: [
			{
				displayName: 'Event Type',
				name: 'event',
				type: 'options',
				options: [
					{
						name: 'All Events',
						value: '*',
						description: 'Trigger on any Zentinelle event',
					},
					{
						name: 'Policy Violation',
						value: 'policy_violation',
						description: 'When a policy blocks an action',
					},
					{
						name: 'Alert',
						value: 'alert',
						description: 'When an alert is raised',
					},
					{
						name: 'Agent Registered',
						value: 'agent_registered',
						description: 'When a new agent registers',
					},
					{
						name: 'Human Approval Required',
						value: 'human_approval_required',
						description: 'When human-in-the-loop approval is needed',
					},
					{
						name: 'Cost Threshold',
						value: 'cost_threshold',
						description: 'When cost exceeds threshold',
					},
					{
						name: 'Rate Limit',
						value: 'rate_limit',
						description: 'When rate limit is approached or exceeded',
					},
				],
				default: '*',
				description: 'Event type to trigger on',
			},
			{
				displayName: 'Webhook Secret',
				name: 'webhookSecret',
				type: 'string',
				typeOptions: { password: true },
				default: '',
				description: 'Secret to validate webhook authenticity',
			},
		],
	};

	webhookMethods = {
		default: {
			async checkExists(this: IHookFunctions): Promise<boolean> {
				// In production, would check if webhook is registered with Zentinelle
				return true;
			},
			async create(this: IHookFunctions): Promise<boolean> {
				// In production, would register webhook URL with Zentinelle
				const webhookUrl = this.getNodeWebhookUrl('default');
				console.log(`Zentinelle webhook URL: ${webhookUrl}`);
				return true;
			},
			async delete(this: IHookFunctions): Promise<boolean> {
				// In production, would unregister webhook from Zentinelle
				return true;
			},
		},
	};

	async webhook(this: IWebhookFunctions): Promise<IWebhookResponseData> {
		const req = this.getRequestObject();
		const body = req.body;

		const event = this.getNodeParameter('event') as string;
		const webhookSecret = this.getNodeParameter('webhookSecret', '') as string;

		// Validate webhook secret if configured
		if (webhookSecret) {
			const signature = req.headers['x-zentinelle-signature'];
			// In production, would validate HMAC signature
			if (!signature) {
				return {
					webhookResponse: { status: 'error', message: 'Missing signature' },
				};
			}
		}

		// Filter by event type
		if (event !== '*' && body.event_type !== event) {
			return {
				webhookResponse: { status: 'ignored', message: 'Event type not matched' },
			};
		}

		// Return the webhook data
		return {
			workflowData: [
				[
					{
						json: {
							eventType: body.event_type,
							agentId: body.agent_id,
							userId: body.user_id,
							action: body.action,
							timestamp: body.timestamp,
							payload: body.payload || {},
							// Flatten important fields for easy access
							...(body.payload || {}),
						},
					},
				],
			],
		};
	}
}
