using System.Text.Json.Serialization;

namespace Zentinelle.Models;

/// <summary>
/// Result of a heartbeat request.
/// </summary>
public class HeartbeatResult
{
    /// <summary>
    /// Whether the heartbeat was accepted.
    /// </summary>
    [JsonPropertyName("acknowledged")]
    public bool Acknowledged { get; set; } = true;

    /// <summary>
    /// Explicit config-change signal from the service.
    /// </summary>
    [JsonPropertyName("config_changed")]
    public bool ConfigChanged { get; set; }

    /// <summary>
    /// Legacy drift signal used by some deployments.
    /// </summary>
    [JsonPropertyName("drift_detected")]
    public bool DriftDetected { get; set; }

    /// <summary>
    /// Legacy sync-required signal used by some deployments.
    /// </summary>
    [JsonPropertyName("sync_required")]
    public bool SyncRequired { get; set; }

    /// <summary>
    /// Suggested next heartbeat interval.
    /// </summary>
    [JsonPropertyName("next_heartbeat_seconds")]
    public int NextHeartbeatSeconds { get; set; } = 60;

    /// <summary>
    /// Returns true when any config-refresh signal is present.
    /// </summary>
    public bool HasConfigChangeSignal => ConfigChanged || DriftDetected || SyncRequired;
}
