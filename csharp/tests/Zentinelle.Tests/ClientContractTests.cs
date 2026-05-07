using System.Net;
using System.Text.Json;
using Zentinelle;
using Zentinelle.Models;
using Xunit;

namespace Zentinelle.Tests;

public class ClientContractTests
{
    [Fact]
    public void Constructor_AcceptsBootstrapToken()
    {
        var options = new ZentinelleOptions
        {
            ApiKey = "bt_test_tenant_bootstrap123",
            AgentType = "csharp-agent",
            BaseUrl = "https://api.zentinelle.ai",
        };

        var client = new ZentinelleClient(options);
        Assert.NotNull(client);
    }

    [Fact]
    public void Constructor_AcceptsAgentKey()
    {
        var options = new ZentinelleOptions
        {
            ApiKey = "sk_agent_runtime_key_123",
            AgentType = "csharp-agent",
            BaseUrl = "https://api.zentinelle.ai",
        };

        var client = new ZentinelleClient(options);
        Assert.NotNull(client);
    }

    [Fact]
    public void Constructor_RequiresApiKey()
    {
        Assert.Throws<ArgumentException>(() =>
        {
            new ZentinelleClient(new ZentinelleOptions
            {
                ApiKey = "",
                AgentType = "test",
            });
        });
    }

    [Fact]
    public void Constructor_RequiresAgentType()
    {
        Assert.Throws<ArgumentException>(() =>
        {
            new ZentinelleClient(new ZentinelleOptions
            {
                ApiKey = "sk_agent_test_key_123",
                AgentType = "",
            });
        });
    }

    [Fact]
    public void DefaultBaseUrl_IsCloud()
    {
        var options = new ZentinelleOptions
        {
            ApiKey = "sk_agent_test_key_123",
            AgentType = "test",
        };
        Assert.Equal("https://api.zentinelle.ai", options.BaseUrl);
    }

    [Fact]
    public void DefaultEndpoint_IsCloud()
    {
        var options = new ZentinelleOptions
        {
            ApiKey = "sk_agent_test_key_123",
            AgentType = "test",
        };

        var client = new ZentinelleClient(options);
        Assert.NotNull(client);
    }
}

public class RegisterResultTests
{
    [Fact]
    public void RegisterResult_DeserializesFromJson()
    {
        var json = """
        {
            "agent_id": "test-agent-001",
            "api_key": "sk_agent_runtime_key",
            "config": { "heartbeat_interval_seconds": 60 },
            "policies": []
        }
        """;

        var result = JsonSerializer.Deserialize<RegisterResult>(json, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        });

        Assert.NotNull(result);
        Assert.Equal("test-agent-001", result.AgentId);
        Assert.Equal("sk_agent_runtime_key", result.ApiKey);
    }
}

public class EvaluateResultTests
{
    [Fact]
    public void EvaluateResult_DeserializesAllowed()
    {
        var json = """
        {
            "allowed": true,
            "reason": null,
            "policies_evaluated": [],
            "warnings": [],
            "context": {}
        }
        """;

        var result = JsonSerializer.Deserialize<EvaluateResult>(json, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        });

        Assert.NotNull(result);
        Assert.True(result.Allowed);
    }

    [Fact]
    public void EvaluateResult_DeserializesBlocked()
    {
        var json = """
        {
            "allowed": false,
            "reason": "Tool shell is denied",
            "policies_evaluated": [
                {
                    "id": "policy-1",
                    "name": "Block shell",
                    "type": "tool_permission",
                    "result": "fail",
                    "message": "Tool shell is denied"
                }
            ],
            "warnings": []
        }
        """;

        var result = JsonSerializer.Deserialize<EvaluateResult>(json, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        });

        Assert.NotNull(result);
        Assert.False(result.Allowed);
        Assert.Equal("Tool shell is denied", result.Reason);
    }
}

public class ConfigResultTests
{
    [Fact]
    public void ConfigResult_DeserializesWithPolicies()
    {
        var json = """
        {
            "agent_id": "test-agent",
            "config": { "heartbeat_interval_seconds": 60 },
            "policies": [
                {
                    "id": "p1",
                    "name": "Rate Limit",
                    "type": "rate_limit",
                    "enforcement": "enforce",
                    "config": { "requests_per_minute": 100 }
                }
            ],
            "updated_at": "2026-05-07T00:00:00Z"
        }
        """;

        var result = JsonSerializer.Deserialize<ConfigResult>(json, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        });

        Assert.NotNull(result);
        Assert.Equal("test-agent", result.AgentId);
    }
}

public class HeartbeatResultTests
{
    [Fact]
    public void HeartbeatResult_DeserializesWithConfigChanged()
    {
        var json = """
        {
            "acknowledged": true,
            "config_changed": true,
            "next_heartbeat_seconds": 30
        }
        """;

        var result = JsonSerializer.Deserialize<HeartbeatResult>(json, new JsonSerializerOptions
        {
            PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
        });

        Assert.NotNull(result);
        Assert.True(result.Acknowledged);
        Assert.True(result.ConfigChanged);
        Assert.Equal(30, result.NextHeartbeatSeconds);
    }

    [Fact]
    public void HeartbeatResult_HasConfigChangeSignal_WhenDriftDetected()
    {
        var result = new HeartbeatResult
        {
            Acknowledged = true,
            DriftDetected = true,
        };

        Assert.True(result.HasConfigChangeSignal);
    }
}
