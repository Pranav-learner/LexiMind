// Combined login / register screen. Minimal by design — auth exists to give workspaces a
// real owner, not to be a product surface yet.

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { ApiError } from "../api/client";

export default function Login() {
  const { login, register } = useAuth();
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      if (mode === "login") await login(email, password);
      else await register(email, password, displayName);
      navigate("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="ws-auth-screen">
      <form className="ws-auth-card" onSubmit={submit}>
        <div className="ws-brand">
          <span className="ws-brand-mark">🧠</span>
          <h1>LexiMind</h1>
        </div>
        <p className="ws-auth-sub">Your AI knowledge workspace</p>

        {mode === "register" && (
          <label className="ws-field">
            <span>Display name</span>
            <input value={displayName} onChange={(e) => setDisplayName(e.target.value)} placeholder="Ada" />
          </label>
        )}
        <label className="ws-field">
          <span>Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
        </label>
        <label className="ws-field">
          <span>Password</span>
          <input
            type="password"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="At least 8 characters"
          />
        </label>

        {error && <div className="ws-error-banner">{error}</div>}

        <button className="ws-btn primary full" type="submit" disabled={busy}>
          {busy ? "Please wait…" : mode === "login" ? "Log in" : "Create account"}
        </button>

        <p className="ws-auth-switch">
          {mode === "login" ? "New to LexiMind?" : "Already have an account?"}{" "}
          <button
            type="button"
            className="ws-link"
            onClick={() => {
              setMode(mode === "login" ? "register" : "login");
              setError(null);
            }}
          >
            {mode === "login" ? "Create one" : "Log in"}
          </button>
        </p>
      </form>
    </div>
  );
}
