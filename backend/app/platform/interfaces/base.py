"""Base interface definition for platform provider components."""
from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseProvider(ABC):
    """Common interface protocol for all LexiMind infrastructure providers."""
    
    @abstractmethod
    def check_health(self) -> Dict[str, Any]:
        """Check the health status of this provider.
        
        Returns:
            Dict containing status ('healthy', 'unhealthy', 'degraded') and metadata.
        """
        pass
