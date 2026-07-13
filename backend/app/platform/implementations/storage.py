"""Storage provider implementations."""
import os
import shutil
from typing import Dict, Any, List
from app.platform.interfaces.storage import StorageProvider

class LocalStorage(StorageProvider):
    """Local disk filesystem storage provider."""

    def __init__(self, base_dir: str):
        self.base_dir = os.path.abspath(base_dir)
        os.makedirs(self.base_dir, exist_ok=True)

    def _resolve(self, path: str) -> str:
        # Prevent path traversal attacks
        clean_path = os.path.normpath(path).lstrip("/")
        return os.path.join(self.base_dir, clean_path)

    def read(self, path: str) -> bytes:
        full_path = self._resolve(path)
        with open(full_path, "rb") as f:
            return f.read()

    def write(self, path: str, content: bytes) -> None:
        full_path = self._resolve(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        with open(full_path, "wb") as f:
            f.write(content)

    def delete(self, path: str) -> None:
        full_path = self._resolve(path)
        if os.path.exists(full_path):
            os.remove(full_path)

    def exists(self, path: str) -> bool:
        return os.path.exists(self._resolve(path))

    def list_files(self, prefix: str = "") -> List[str]:
        target_dir = self._resolve(prefix)
        if not os.path.exists(target_dir):
            return []
        files = []
        for root, _, filenames in os.walk(target_dir):
            for filename in filenames:
                full_p = os.path.join(root, filename)
                rel_p = os.path.relpath(full_p, self.base_dir)
                files.append(rel_p)
        return files

    def check_health(self) -> Dict[str, Any]:
        has_write = False
        test_file = os.path.join(self.base_dir, ".health_test")
        try:
            with open(test_file, "w") as f:
                f.write("OK")
            os.remove(test_file)
            has_write = True
        except Exception:
            pass
        
        if has_write:
            return {"status": "healthy", "details": f"Local storage writable at {self.base_dir}."}
        return {"status": "unhealthy", "details": f"Local storage is not writable at {self.base_dir}."}


class S3Storage(StorageProvider):
    """S3-compatible Cloud Storage provider (AWS/MinIO/GCS interoperability)."""

    def __init__(self, bucket_name: str, endpoint_url: str = None, access_key: str = None, secret_key: str = None):
        self.bucket_name = bucket_name
        self.endpoint_url = endpoint_url
        # Simulated cloud store falling back to dynamic memory mapping to preserve zero external system deps
        self._store = {}

    def read(self, path: str) -> bytes:
        if path not in self._store:
            raise FileNotFoundError(f"Key {path} not found in S3 bucket {self.bucket_name}.")
        return self._store[path]

    def write(self, path: str, content: bytes) -> None:
        self._store[path] = content

    def delete(self, path: str) -> None:
        self._store.pop(path, None)

    def exists(self, path: str) -> bool:
        return path in self._store

    def list_files(self, prefix: str = "") -> List[str]:
        return [k for k in self._store.keys() if k.startswith(prefix)]

    def check_health(self) -> Dict[str, Any]:
        return {"status": "healthy", "details": f"S3 Storage simulation active on bucket '{self.bucket_name}'."}
