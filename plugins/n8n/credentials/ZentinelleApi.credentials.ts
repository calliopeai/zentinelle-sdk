import {
	IAuthenticateGeneric,
	ICredentialTestRequest,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

export class ZentinelleApi implements ICredentialType {
	name = 'zentinelleApi';
	displayName = 'Zentinelle API';
	documentationUrl = 'https://docs.zentinelle.ai/integrations/n8n';
	properties: INodeProperties[] = [
		{
			displayName: 'API Key',
			name: 'apiKey',
			type: 'string',
			typeOptions: { password: true },
			default: '',
			required: true,
			description: 'Your Zentinelle API key (starts with sk_agent_)',
		},
		{
			displayName: 'Endpoint',
			name: 'endpoint',
			type: 'string',
			default: 'https://api.zentinelle.ai',
			description: 'Zentinelle API endpoint (use default for cloud)',
		},
		{
			displayName: 'Agent Type',
			name: 'agentType',
			type: 'string',
			default: 'n8n',
			description: 'Agent type identifier for telemetry',
		},
	];

	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: {
			headers: {
				'X-Zentinelle-Key': '={{$credentials.apiKey}}',
			},
		},
	};

	test: ICredentialTestRequest = {
		request: {
			baseURL: '={{$credentials.endpoint}}',
			url: '/api/v1/health',
			method: 'GET',
		},
	};
}
