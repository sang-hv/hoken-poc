import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "./api";
import type { Role, User } from "./types";

const RANK: Record<Role, number> = { viewer: 0, reviewer: 1, admin: 2 };

interface AuthCtx {
  user: User | null;
  loading: boolean;
  can: (role: Role) => boolean;
  logout: () => Promise<void>;
  refresh: () => void;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api.get<User>("/auth/me"),
    retry: false,
    staleTime: 60_000,
  });

  useEffect(() => {
    const onUnauthorized = () => {
      qc.setQueryData(["me"], null);
      nav("/login");
    };
    window.addEventListener("hoken:unauthorized", onUnauthorized);
    return () => window.removeEventListener("hoken:unauthorized", onUnauthorized);
  }, [qc, nav]);

  const user = me.data ?? null;
  const value: AuthCtx = {
    user,
    loading: me.isLoading,
    can: (role) => !!user && RANK[user.role] >= RANK[role],
    logout: async () => {
      await api.post("/auth/logout");
      qc.clear();
      nav("/login");
    },
    refresh: () => qc.invalidateQueries({ queryKey: ["me"] }),
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("AuthProvider missing");
  return c;
}
