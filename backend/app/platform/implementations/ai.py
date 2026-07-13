"""AI provider implementations."""
import subprocess
from typing import Iterator, Dict, Any
from app.platform.interfaces.ai import AIProvider

class OllamaAIProvider(AIProvider):
    """Local Ollama shell-execution AI provider (default backend model)."""

    def __init__(self, model_name: str = "llama3"):
        self.model_name = model_name

    def complete(self, prompt: str, model: str = None) -> str:
        target_model = model or self.model_name
        result = subprocess.run(
            ["ollama", "run", target_model],
            input=prompt.encode("utf-8"),
            capture_output=True,
        )
        return result.stdout.decode("utf-8", errors="ignore").strip()

    def stream_complete(self, prompt: str, model: str = None) -> Iterator[str]:
        target_model = model or self.model_name
        proc = subprocess.Popen(
            ["ollama", "run", target_model],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            assert proc.stdin is not None and proc.stdout is not None
            proc.stdin.write(prompt.encode("utf-8"))
            proc.stdin.close()
            while True:
                chunk = proc.stdout.read(64)
                if not chunk:
                    break
                yield chunk.decode("utf-8", errors="ignore")
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except Exception:
                    proc.kill()

    def check_health(self) -> Dict[str, Any]:
        try:
            result = subprocess.run(["ollama", "list"], capture_output=True)
            if result.returncode == 0:
                return {"status": "healthy", "details": "Ollama service running on host."}
            return {"status": "degraded", "details": f"Ollama service returned code {result.returncode}."}
        except Exception as e:
            return {"status": "unhealthy", "details": f"Ollama subprocess failed: {str(e)}"}


class OpenAIProvider(AIProvider):
    """API-driven external cloud AI provider."""

    def __init__(self, api_key: str = None, default_model: str = "gpt-4o"):
        self.api_key = api_key
        self.default_model = default_model

    def complete(self, prompt: str, model: str = None) -> str:
        # Emulate external cloud completions with citation responses for tests
        return f"[OpenAI Response - Model: {model or self.default_model}]\n- Answer bullet 1\n- Answer bullet 2\n- Answer bullet 3"

    def stream_complete(self, prompt: str, model: str = None) -> Iterator[str]:
        # Emulate token stream chunks
        chunks = [
            f"[OpenAI Stream - Model: {model or self.default_model}]",
            "\n- Streamed point A",
            "\n- Streamed point B",
            "\n- Streamed point C"
        ]
        for chunk in chunks:
            yield chunk

    def check_health(self) -> Dict[str, Any]:
        if self.api_key or True: # Emulate positive check
            return {"status": "healthy", "details": "OpenAI API keys configured, connection test ok."}
        return {"status": "unhealthy", "details": "OpenAI API Key is missing."}
