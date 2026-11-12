export interface AuthUser {
  id: number;
  role: "OWNER" | "EMPLOYEE";
  full_name: string;
  email?: string;
  employee_code?: string;
  department?: string;
  preferred_language: "en" | "hi" | "pa";
}

export interface EffectiveAccess {
  user_id: number;
  role: string;
  visible_pages: string[];
  accessible_location_ids: number[];
  editable_fields: Record<string, string[]>;
  allowed_actions: string[];
  can_export: boolean;
  assigned_tasks: Array<{
    id: number;
    task_code: string;
    task_type: string;
    title: string;
    status: string;
    location_id: number | null;
    deadline_at: string | null;
  }>;
}

class BossApiClient {
  private token: string | null = null;

  setToken(token: string | null) {
    this.token = token;
  }

  async request<T>(path: string, options: RequestInit = {}): Promise<T> {
    const headers: Record<string, string> = {
      ...(options.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(options.headers as Record<string, string> | undefined),
    };
    if (this.token) {
      headers["Authorization"] = `Bearer ${this.token}`;
    }

    const res = await fetch(path, {
      ...options,
      headers,
      credentials: "include",
    });

    const text = await res.text();
    let data: unknown = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }

    if (!res.ok) {
      const detail =
        typeof data === "object" && data !== null && "detail" in data
          ? String((data as { detail: unknown }).detail)
          : `Request failed (${res.status})`;
      throw new Error(detail);
    }
    return data as T;
  }
}

export const api = new BossApiClient();

