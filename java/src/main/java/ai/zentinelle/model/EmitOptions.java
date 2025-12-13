package ai.zentinelle.model;

/**
 * Options for event emission.
 */
public class EmitOptions {

    private final EventCategory category;
    private final String userId;

    private EmitOptions(Builder builder) {
        this.category = builder.category;
        this.userId = builder.userId;
    }

    public EventCategory getCategory() { return category; }
    public String getUserId() { return userId; }

    public static Builder builder() { return new Builder(); }

    public static class Builder {
        private EventCategory category;
        private String userId;

        public Builder category(EventCategory category) { this.category = category; return this; }
        public Builder userId(String userId) { this.userId = userId; return this; }

        public EmitOptions build() { return new EmitOptions(this); }
    }
}
