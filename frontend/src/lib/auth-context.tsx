"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/api-client";
import type { User } from "@/lib/types";

type AuthState = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName?: string) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
};

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  const refresh = useCallback(async () => {
    try {
      const me = await auth.me();
      setUser(me);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const login = useCallback(
    async (email: string, password: string) => {
      await auth.login({ email, password });
      await refresh();
      router.push("/dashboard");
    },
    [refresh, router],
  );

  const register = useCallback(
    async (email: string, password: string, full_name?: string) => {
      await auth.register({ email, password, full_name });
      await refresh();
      router.push("/dashboard");
    },
    [refresh, router],
  );

  const logout = useCallback(async () => {
    try {
      await auth.logout();
    } finally {
      setUser(null);
      router.push("/login");
    }
  }, [router]);

  return (
    <Ctx.Provider value={{ user, loading, login, register, logout, refresh }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
