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

const AUTH_ACCESS_TOKEN_KEY = 'orthanc_access_token';
const AUTH_REFRESH_TOKEN_KEY = 'orthanc_refresh_token';

function decodeJWT(token: string): { sub: string; username?: string } | null {
  try {
    const payload = token.split('.')[1];
    return JSON.parse(atob(payload.replace(/-/g, '+').replace(/_/g, '/')));
  } catch {
    return null;
  }
}

function loadStoredAuth(): { access: string | null; refresh: string | null } {
  const access = localStorage.getItem(AUTH_ACCESS_TOKEN_KEY);
  const refresh = localStorage.getItem(AUTH_REFRESH_TOKEN_KEY);
  return { access, refresh };
}

export const useAuthStore = create<AuthState>((set, get) => {
  const { access, refresh } = loadStoredAuth();
  const decoded = access ? decodeJWT(access) : null;
  const user: User | null = decoded
    ? { id: decoded.sub, username: decoded.username ?? decoded.sub }
    : null;

  return {
    token: access,
    refreshToken: refresh,
    user,
    isAuthenticated: !!access,

    setTokens: (accessToken: string, refreshToken: string) => {
      const decodedToken = decodeJWT(accessToken);
      const decodedUser: User | null = decodedToken
        ? { id: decodedToken.sub, username: decodedToken.username ?? decodedToken.sub }
        : null;

      localStorage.setItem(AUTH_ACCESS_TOKEN_KEY, accessToken);
      localStorage.setItem(AUTH_REFRESH_TOKEN_KEY, refreshToken);
      set({ token: accessToken, refreshToken, user: decodedUser, isAuthenticated: true });
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
        localStorage.removeItem(AUTH_ACCESS_TOKEN_KEY);
        localStorage.removeItem(AUTH_REFRESH_TOKEN_KEY);
        set({ token: null, refreshToken: null, user: null, isAuthenticated: false });
      }
    },
  };
});
