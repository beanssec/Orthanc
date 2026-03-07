import axios from 'axios';
import { useAuthStore } from '../stores/authStore';

const api = axios.create({
  baseURL: window.location.hostname === 'localhost' || window.location.hostname.match(/^(\d+\.){3}\d+$/)
    ? `http://${window.location.hostname}:8000`
    : '/api',
  headers: { 'Content-Type': 'application/json' },
  // Serialize arrays as repeated params: source_types=a&source_types=b (FastAPI style)
  paramsSerializer: { indexes: null },
});

// Attach Bearer token
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Handle 401 → try refresh
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      const refreshToken = useAuthStore.getState().refreshToken;
      if (refreshToken) {
        try {
          const res = await axios.post(
            `${api.defaults.baseURL}/auth/refresh`,
            null,
            { params: { token: refreshToken } }
          );
          const { access_token, refresh_token } = res.data;
          useAuthStore.getState().setTokens(access_token, refresh_token);
          originalRequest.headers.Authorization = `Bearer ${access_token}`;
          return api(originalRequest);
        } catch {
          useAuthStore.getState().logout();
          window.location.href = '/login';
        }
      } else {
        useAuthStore.getState().logout();
        window.location.href = '/login';
      }
    }
    return Promise.reject(error);
  }
);

export default api;
