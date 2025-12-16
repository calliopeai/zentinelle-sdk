"""
Governed memory plugin for Microsoft Agent Framework.
"""
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from zentinelle import ZentinelleClient

logger = logging.getLogger(__name__)


class ZentinelleMemoryPlugin:
    """
    Pluggable memory with governance controls for Microsoft Agent Framework.

    Provides:
    - Data retention enforcement
    - PII detection before storage
    - Access logging for compliance
    - Automatic expiration

    Usage:
        from zentinelle_ms_agent import ZentinelleMemoryPlugin

        memory = ZentinelleMemoryPlugin(
            api_key="sk_agent_...",
            retention_hours=24,
            detect_pii=True,
        )

        # Store with governance
        await memory.store("key", "value", user_id="user123")

        # Retrieve with access logging
        value = await memory.retrieve("key", user_id="user123")
    """

    def __init__(
        self,
        api_key: str,
        endpoint: Optional[str] = None,
        retention_hours: int = 24,
        max_items: int = 1000,
        detect_pii: bool = True,
        block_pii: bool = False,
        **client_kwargs,
    ):
        """
        Initialize memory plugin.

        Args:
            api_key: Zentinelle API key
            endpoint: Custom Zentinelle endpoint
            retention_hours: Hours to retain items
            max_items: Maximum items to store
            detect_pii: Enable PII detection
            block_pii: Block storage of PII (vs redact)
            **client_kwargs: Additional ZentinelleClient args
        """
        self.client = ZentinelleClient(
            api_key=api_key,
            agent_type="ms-agent-framework-memory",
            endpoint=endpoint,
            **client_kwargs,
        )
        self.retention_hours = retention_hours
        self.max_items = max_items
        self.detect_pii = detect_pii
        self.block_pii = block_pii

        # In-memory storage (swap for external store in production)
        self._storage: Dict[str, Dict[str, Any]] = {}
        self._access_log: List[Dict] = []

    async def store(
        self,
        key: str,
        value: Any,
        user_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
        ttl_hours: Optional[int] = None,
    ) -> bool:
        """
        Store a value with governance checks.

        Args:
            key: Storage key
            value: Value to store
            user_id: User identifier
            metadata: Additional metadata
            ttl_hours: Override retention hours

        Returns:
            True if stored successfully
        """
        # Check capacity
        if len(self._storage) >= self.max_items:
            self._cleanup_expired()
            if len(self._storage) >= self.max_items:
                logger.warning(f"Memory capacity exceeded: {self.max_items}")
                return False

        # PII check if enabled
        if self.detect_pii:
            result = self.client.evaluate(
                action='memory_store',
                user_id=user_id,
                context={
                    'key': key,
                    'value_preview': str(value)[:500],
                    'check_pii': True,
                },
            )

            if not result.allowed:
                if self.block_pii:
                    logger.warning(f"Blocked PII storage for key: {key}")
                    self.client.emit('memory_pii_blocked', {
                        'key': key,
                        'reason': result.reason,
                    }, category='compliance', user_id=user_id)
                    return False
                else:
                    # Could redact here if Zentinelle returns redacted version
                    logger.info(f"PII detected in key: {key}")

        # Store item
        expires_at = datetime.utcnow() + timedelta(
            hours=ttl_hours or self.retention_hours
        )

        self._storage[key] = {
            'value': value,
            'metadata': metadata or {},
            'user_id': user_id,
            'created_at': datetime.utcnow().isoformat(),
            'expires_at': expires_at.isoformat(),
        }

        self.client.emit('memory_store', {
            'key': key,
            'value_size': len(str(value)),
            'ttl_hours': ttl_hours or self.retention_hours,
        }, category='audit', user_id=user_id)

        return True

    async def retrieve(
        self,
        key: str,
        user_id: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Retrieve a value with access logging.

        Args:
            key: Storage key
            user_id: User identifier

        Returns:
            Stored value or None
        """
        item = self._storage.get(key)

        if not item:
            return None

        # Check expiration
        expires_at = datetime.fromisoformat(item['expires_at'])
        if datetime.utcnow() > expires_at:
            del self._storage[key]
            return None

        # Log access
        self.client.emit('memory_retrieve', {
            'key': key,
            'original_user_id': item.get('user_id'),
        }, category='audit', user_id=user_id)

        return item['value']

    async def delete(
        self,
        key: str,
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Delete a value.

        Args:
            key: Storage key
            user_id: User identifier

        Returns:
            True if deleted
        """
        if key in self._storage:
            del self._storage[key]

            self.client.emit('memory_delete', {
                'key': key,
            }, category='audit', user_id=user_id)

            return True
        return False

    async def search(
        self,
        query: str,
        user_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Search memory items.

        Args:
            query: Search query
            user_id: User identifier
            limit: Maximum results

        Returns:
            List of matching items
        """
        self._cleanup_expired()

        results = []
        for key, item in self._storage.items():
            if query.lower() in str(item['value']).lower():
                results.append({
                    'key': key,
                    'value': item['value'],
                    'metadata': item['metadata'],
                })
                if len(results) >= limit:
                    break

        self.client.emit('memory_search', {
            'query_length': len(query),
            'results_count': len(results),
        }, category='audit', user_id=user_id)

        return results

    async def clear_user_data(
        self,
        user_id: str,
        requester_id: Optional[str] = None,
    ) -> int:
        """
        Clear all data for a specific user (GDPR right to erasure).

        Args:
            user_id: User whose data to clear
            requester_id: Who requested the deletion

        Returns:
            Number of items deleted
        """
        keys_to_delete = [
            key for key, item in self._storage.items()
            if item.get('user_id') == user_id
        ]

        for key in keys_to_delete:
            del self._storage[key]

        self.client.emit('memory_user_data_cleared', {
            'target_user_id': user_id,
            'items_deleted': len(keys_to_delete),
        }, category='compliance', user_id=requester_id)

        return len(keys_to_delete)

    def _cleanup_expired(self) -> int:
        """Remove expired items."""
        now = datetime.utcnow()
        expired_keys = [
            key for key, item in self._storage.items()
            if datetime.fromisoformat(item['expires_at']) < now
        ]

        for key in expired_keys:
            del self._storage[key]

        if expired_keys:
            logger.debug(f"Cleaned up {len(expired_keys)} expired memory items")

        return len(expired_keys)

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        self._cleanup_expired()
        return {
            'total_items': len(self._storage),
            'max_items': self.max_items,
            'retention_hours': self.retention_hours,
        }

    def shutdown(self) -> None:
        """Shutdown and flush events."""
        self.client.shutdown()
