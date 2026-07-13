"""SSO Provider Adapters (OIDC, SAML, Okta, Entra ID, Google, Keycloak).

Defines a generic interface and offline-friendly simulated adapters to test
SAML/OIDC flows without external connectivity.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from urllib.parse import urlencode


class SSOProviderAdapter(ABC):
    @abstractmethod
    def get_login_url(self, redirect_uri: str, state: str | None = None) -> str:
        """Generate the authorization redirect URL."""
        pass

    @abstractmethod
    def authenticate_code(self, code: str, redirect_uri: str) -> dict[str, str]:
        """Exchanges an authorization code for validated user profile details."""
        pass


class OIDCAdapter(SSOProviderAdapter):
    def __init__(self, client_id: str, client_secret: str, issuer_url: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.issuer_url = issuer_url

    def get_login_url(self, redirect_uri: str, state: str | None = None) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
        }
        if state:
            params["state"] = state
        return f"{self.issuer_url}/oauth/authorize?{urlencode(params)}"

    def authenticate_code(self, code: str, redirect_uri: str) -> dict[str, str]:
        # Offline simulation fallback for testing / development
        if code.startswith("sim_"):
            username = code.split("_")[1]
            return {
                "email": f"{username}@sso-oidc.com",
                "display_name": username.capitalize(),
                "external_id": f"oidc_{username}",
            }
        # In production, we would perform an HTTP request to self.issuer_url/token
        # Here we return a stub that represents the simulated profile mapping.
        return {
            "email": "federated-oidc@example.com",
            "display_name": "Federated OIDC User",
            "external_id": f"oidc_{code}",
        }


class SAMLAdapter(SSOProviderAdapter):
    def __init__(self, entity_id: str, sso_url: str, x509_cert: str):
        self.entity_id = entity_id
        self.sso_url = sso_url
        self.x509_cert = x509_cert

    def get_login_url(self, redirect_uri: str, state: str | None = None) -> str:
        params = {
            "SAMLRequest": "simulated_saml_request_payload",
            "RelayState": state or redirect_uri,
        }
        return f"{self.sso_url}?{urlencode(params)}"

    def authenticate_code(self, code: str, redirect_uri: str) -> dict[str, str]:
        # SAML response simulation
        if code.startswith("sim_"):
            username = code.split("_")[1]
            return {
                "email": f"{username}@sso-saml.com",
                "display_name": username.capitalize(),
                "external_id": f"saml_{username}",
            }
        return {
            "email": "federated-saml@example.com",
            "display_name": "Federated SAML User",
            "external_id": f"saml_{code}",
        }


class OktaAdapter(OIDCAdapter):
    def __init__(self, client_id: str, client_secret: str, org_url: str):
        super().__init__(client_id, client_secret, f"https://{org_url}/oauth2/default")


class MicrosoftEntraAdapter(OIDCAdapter):
    def __init__(self, client_id: str, client_secret: str, tenant_id: str):
        super().__init__(client_id, client_secret, f"https://login.microsoftonline.com/{tenant_id}")


class GoogleWorkspaceAdapter(OIDCAdapter):
    def __init__(self, client_id: str, client_secret: str):
        super().__init__(client_id, client_secret, "https://accounts.google.com")


class KeycloakAdapter(OIDCAdapter):
    def __init__(self, client_id: str, client_secret: str, server_url: str, realm: str):
        super().__init__(client_id, client_secret, f"{server_url}/realms/{realm}")


def get_sso_adapter(provider_type: str, config: dict) -> SSOProviderAdapter:
    """Factory to load corresponding SSO adapter."""
    p_lower = provider_type.lower()
    client_id = config.get("client_id", "sim_client")
    client_secret = config.get("client_secret", "sim_secret")

    if p_lower == "google":
        return GoogleWorkspaceAdapter(client_id, client_secret)
    elif p_lower == "okta":
        return OktaAdapter(client_id, client_secret, config.get("org_url", "okta.com"))
    elif p_lower == "entra" or p_lower == "microsoft":
        return MicrosoftEntraAdapter(client_id, client_secret, config.get("tenant_id", "common"))
    elif p_lower == "keycloak":
        return KeycloakAdapter(
            client_id,
            client_secret,
            config.get("server_url", "http://localhost:8080"),
            config.get("realm", "master"),
        )
    elif p_lower == "saml":
        return SAMLAdapter(
            config.get("entity_id", "leximind"),
            config.get("sso_url", "http://saml-idp/sso"),
            config.get("x509_cert", ""),
        )
    else:
        return OIDCAdapter(client_id, client_secret, config.get("issuer_url", "http://oidc-provider"))
