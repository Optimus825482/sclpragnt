"use client";

import { createContext, useContext } from "react";

export type AuthUser = {
  username: string | null;
  role: string | null;
  /** Oturumu kapat (Sidebar altındaki "OTURUMU KAPAT" butonu çağırır). */
  logout?: () => Promise<void>;
};

export const AuthContext = createContext<AuthUser>({ username: null, role: null });

export function useAuth(): AuthUser {
  return useContext(AuthContext);
}
