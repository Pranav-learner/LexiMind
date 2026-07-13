"""Feature Flag Framework for LexiMind."""
from typing import Dict, Any, Optional
import hashlib

class FeatureFlagManager:
    """Manages policy-driven, dynamic feature flags with rollout support."""

    def __init__(self):
        # Default flag catalog
        self._flags: Dict[str, Dict[str, Any]] = {
            "enable_mcp": {
                "default": True,
                "percentage": 100,
                "overrides": {}
            },
            "enable_canary": {
                "default": False,
                "percentage": 20, # 20% default rollout
                "overrides": {}
            },
            "maintenance_mode": {
                "default": False,
                "percentage": 0,
                "overrides": {}
            },
            "enable_vector_search": {
                "default": True,
                "percentage": 100,
                "overrides": {}
            },
            "enable_evaluation": {
                "default": True,
                "percentage": 100,
                "overrides": {}
            }
        }
        self._developer_overrides: Dict[str, bool] = {}

    def is_enabled(
        self,
        flag_name: str,
        *,
        user_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        organization_id: Optional[str] = None
    ) -> bool:
        """Evaluate feature flag status based on rules hierarchy:
        
        1. Developer Override
        2. Organization Specific Override
        3. Workspace Specific Override
        4. User Specific Override
        5. Hash-based Percentage Rollout (canary)
        6. Default Flag Value
        """
        # 1. Developer overrides
        if flag_name in self._developer_overrides:
            return self._developer_overrides[flag_name]

        spec = self._flags.get(flag_name)
        if not spec:
            return False

        # 2. Org overrides
        if organization_id and organization_id in spec.get("overrides", {}):
            return spec["overrides"][organization_id]

        # 3. Workspace overrides
        if workspace_id and workspace_id in spec.get("overrides", {}):
            return spec["overrides"][workspace_id]

        # 4. User overrides
        if user_id and user_id in spec.get("overrides", {}):
            return spec["overrides"][user_id]

        # 5. Percentage rollout using hash calculation
        pct = spec.get("percentage", 100)
        if pct >= 100:
            return True
        if pct > 0 and user_id:
            # Deterministic hash mapping user_id to 0-99 integer
            hasher = hashlib.md5(f"{flag_name}:{user_id}".encode("utf-8"))
            val = int(hasher.hexdigest(), 16) % 100
            return val < pct

        # 6. Default
        return spec.get("default", False)

    def set_override(self, flag_name: str, key: str, enabled: bool) -> None:
        """Set override for specific user_id, workspace_id or organization_id."""
        if flag_name not in self._flags:
            self._flags[flag_name] = {"default": False, "percentage": 100, "overrides": {}}
        self._flags[flag_name]["overrides"][key] = enabled

    def set_developer_override(self, flag_name: str, enabled: Optional[bool]) -> None:
        """Set developer global override (ignores all other rules)."""
        if enabled is None:
            self._developer_overrides.pop(flag_name, None)
        else:
            self._developer_overrides[flag_name] = enabled

    def update_percentage(self, flag_name: str, pct: int) -> None:
        """Update percentage rollout rate."""
        if flag_name in self._flags:
            self._flags[flag_name]["percentage"] = max(0, min(100, pct))

    def get_all_flags(self) -> Dict[str, Dict[str, Any]]:
        """Return full flags catalogue status."""
        return {
            name: {
                "default": val["default"],
                "percentage": val["percentage"],
                "overrides": val["overrides"],
                "dev_override": self._developer_overrides.get(name)
            }
            for name, val in self._flags.items()
        }
