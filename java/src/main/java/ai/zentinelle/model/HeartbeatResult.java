package ai.zentinelle.model;

/**
 * Result of a heartbeat.
 */
public class HeartbeatResult {

    private final boolean acknowledged;
    private final boolean configChanged;
    private final int nextHeartbeatSeconds;

    private HeartbeatResult(Builder builder) {
        this.acknowledged = builder.acknowledged;
        this.configChanged = builder.configChanged;
        this.nextHeartbeatSeconds = builder.nextHeartbeatSeconds;
    }

    public boolean isAcknowledged() { return acknowledged; }
    public boolean isConfigChanged() { return configChanged; }
    public int getNextHeartbeatSeconds() { return nextHeartbeatSeconds; }

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private boolean acknowledged = true;
        private boolean configChanged;
        private int nextHeartbeatSeconds = 60;

        public Builder acknowledged(boolean acknowledged) { this.acknowledged = acknowledged; return this; }
        public Builder configChanged(boolean configChanged) { this.configChanged = configChanged; return this; }
        public Builder nextHeartbeatSeconds(int nextHeartbeatSeconds) {
            this.nextHeartbeatSeconds = nextHeartbeatSeconds;
            return this;
        }

        public HeartbeatResult build() { return new HeartbeatResult(this); }
    }
}
