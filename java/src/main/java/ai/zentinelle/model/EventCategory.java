package ai.zentinelle.model;

/**
 * Event category for telemetry.
 */
public enum EventCategory {
    TELEMETRY("telemetry"),
    AUDIT("audit"),
    ALERT("alert"),
    COMPLIANCE("compliance");

    private final String value;

    EventCategory(String value) {
        this.value = value;
    }

    public String getValue() {
        return value;
    }

    public static EventCategory fromValue(String value) {
        for (EventCategory category : values()) {
            if (category.value.equals(value)) {
                return category;
            }
        }
        return TELEMETRY;
    }
}
