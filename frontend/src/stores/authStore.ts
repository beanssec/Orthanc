import { create } from 'zustand';
import api from '../services/api';

interface User {
  id: string;
  username: string;
}

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  user: User | null;
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  setTokens: (access: string, refresh: string) => void;
}

function decodeJWT(token: string): { sub: string; username?: string } | null {
  try {
    const payload = token.split('.')[1];
    return JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
  } catch {
    return null;
  }
}

export const useAuthStore = create<AuthState>((set, get) => ({
  token: null,
  refreshToken: null,
  user: null,
  isAuthenticated: false,

  setTokens: (access: string, refresh: string) => {
    const decoded = decodeJWT(access);
    const user: User | null = decoded
      ? { id: decoded.sub, username: decoded.username ?? decoded.sub }
      : null;
    set({ token: access, refreshToken: refresh, user, isAuthenticated: true });
  },

  login: async (username: string, password: string) => {
    const response = await api.post('/auth/login', { username, password });

    const { access_token, refresh_token } = response.data;
    get().setTokens(access_token, refresh_token ?? '');
  },

  register: async (username: string, password: string) => {
    await api.post('/auth/register', { username, password });
  },

  logout: async () => {
    try {
      const { token } = get();
      if (token) {
        await api.post('/auth/logout');
      }
    } catch {
      // ignore
    } finally {
      set({ token: null, refreshToken: null, user: null, isAuthenticated: false });
    }
  },
}));
