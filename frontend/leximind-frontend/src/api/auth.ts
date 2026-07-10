import { apiRequest } from "./client";
import type { AuthResponse, User } from "../types";

export function register(email: string, password: string, display_name: string) {
  return apiRequest<AuthResponse>("/auth/register", {
    method: "POST",
    auth: false,
    body: { email, password, display_name },
  });
}

export function login(email: string, password: string) {
  return apiRequest<AuthResponse>("/auth/login", {
    method: "POST",
    auth: false,
    body: { email, password },
  });
}

export function me() {
  return apiRequest<User>("/auth/me");
}
