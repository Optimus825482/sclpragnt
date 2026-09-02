"use client";

import { createContext, useContext } from "react";

export type AuthUser = {
  username: string | null;
  role: string | null;
};

export const AuthContext = createContext<AuthUser>({ username: null, role: null });

export function useAuth(): AuthUser {
  return useContext(AuthContext);
}
