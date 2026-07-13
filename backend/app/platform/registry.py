"""Infrastructure registry for resolving platform services (DI container)."""
from typing import Dict, Any, Type, Optional
from app.platform.errors import RegistryError
from app.platform.profiles import DeploymentProfile, ProfileName
from app.platform.interfaces import (
    DatabaseProvider, QueueProvider, StorageProvider,
    VectorStoreProvider, AIProvider, DeploymentProvider,
    SecretProvider, WorkerBackend
)
from app.platform.implementations import (
    SQLiteProvider, PostgreSQLProvider, LocalQueue, RedisQueue,
    LocalStorage, S3Storage, FAISSStore, PgVectorStore,
    OllamaAIProvider, OpenAIProvider, DockerDeployment,
    KubernetesDeployment, EnvSecretProvider
)

class InfrastructureRegistry:
    """Central registry resolving platform services dynamically."""

    def __init__(self, profile: Optional[DeploymentProfile] = None):
        self.profile = profile or DeploymentProfile(ProfileName.DEVELOPMENT)
        self._providers: Dict[Type, Any] = {}
        self._initialize_defaults()

    def _initialize_defaults(self) -> None:
        """Instantiate defaults based on active deployment profile."""
        # 1. Secret Provider
        self.register(SecretProvider, EnvSecretProvider())

        # 2. Database Provider
        if self.profile.default_database_provider == "postgresql":
            # Real PG would use env settings, we pass dummy for fallback safety in unit tests
            self.register(DatabaseProvider, PostgreSQLProvider("postgresql://postgres:postgres@localhost:5432/leximind"))
        else:
            self.register(DatabaseProvider, SQLiteProvider("sqlite:///leximind.db"))

        # 3. Queue Provider
        if self.profile.default_queue_provider == "redis":
            self.register(QueueProvider, RedisQueue("redis://localhost:6379/0"))
        else:
            self.register(QueueProvider, LocalQueue())

        # 4. Storage Provider
        if self.profile.default_storage_provider == "s3":
            self.register(StorageProvider, S3Storage("leximind-assets"))
        else:
            self.register(StorageProvider, LocalStorage("uploaded_pdfs"))

        # 5. Vector Store Provider
        if self.profile.default_vector_store_provider == "pgvector":
            self.register(VectorStoreProvider, PgVectorStore("postgresql://postgres:postgres@localhost:5432/leximind"))
        else:
            self.register(VectorStoreProvider, FAISSStore("vector_index.faiss", "metadata.json"))

        # 6. AI Provider
        if self.profile.default_ai_provider == "openai":
            self.register(AIProvider, OpenAIProvider())
        else:
            self.register(AIProvider, OllamaAIProvider())

        # 7. Deployment Provider
        if self.profile.name in (ProfileName.PRODUCTION, ProfileName.ENTERPRISE):
            self.register(DeploymentProvider, KubernetesDeployment())
        else:
            self.register(DeploymentProvider, DockerDeployment())

    def register(self, interface_class: Type, implementation_instance: Any) -> None:
        """Register a provider implementation instance for an interface class."""
        self._providers[interface_class] = implementation_instance

    def resolve(self, interface_class: Type) -> Any:
        """Resolve the active implementation instance for the given interface class."""
        provider = self._providers.get(interface_class)
        if not provider:
            raise RegistryError(f"No registered provider found for interface: {interface_class.__name__}")
        return provider

    # Helper getters
    def get_database(self) -> DatabaseProvider:
        return self.resolve(DatabaseProvider)

    def get_queue(self) -> QueueProvider:
        return self.resolve(QueueProvider)

    def get_storage(self) -> StorageProvider:
        return self.resolve(StorageProvider)

    def get_vector(self) -> VectorStoreProvider:
        return self.resolve(VectorStoreProvider)

    def get_ai(self) -> AIProvider:
        return self.resolve(AIProvider)

    def get_deployment(self) -> DeploymentProvider:
        return self.resolve(DeploymentProvider)

    def get_secrets(self) -> SecretProvider:
        return self.resolve(SecretProvider)
