package ai.zentinelle.model;

import java.time.Instant;
import java.util.HashMap;
import java.util.Map;

/**
 * Telemetry event.
 */
public class Event {

    private final String type;
    private final EventCategory category;
    private final Map<String, Object> payload;
    private final Instant timestamp;
    private final String userId;

    private Event(Builder builder) {
        this.type = builder.type;
        this.category = builder.category != null ? builder.category : EventCategory.TELEMETRY;
        this.payload = builder.payload != null ? builder.payload : Map.of();
        this.timestamp = builder.timestamp != null ? builder.timestamp : Instant.now();
        this.userId = builder.userId;
    }

    public String getType() { return type; }
    public EventCategory getCategory() { return category; }
    public Map<String, Object> getPayload() { return payload; }
    public Instant getTimestamp() { return timestamp; }
    public String getUserId() { return userId; }

    /**
     * Converts the event to a map for serialization.
     */
    public Map<String, Object> toMap() {
        Map<String, Object> map = new HashMap<>();
        map.put("type", type);
        map.put("category", category.getValue());
        map.put("payload", payload);
        map.put("timestamp", timestamp.toString());
        if (userId != null) {
            map.put("user_id", userId);
        }
        return map;
    }

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private String type;
        private EventCategory category;
        private Map<String, Object> payload;
        private Instant timestamp;
        private String userId;

        public Builder type(String type) { this.type = type; return this; }
        public Builder category(EventCategory category) { this.category = category; return this; }
        public Builder payload(Map<String, Object> payload) { this.payload = payload; return this; }
        public Builder timestamp(Instant timestamp) { this.timestamp = timestamp; return this; }
        public Builder userId(String userId) { this.userId = userId; return this; }

        public Event build() { return new Event(this); }
    }
}
