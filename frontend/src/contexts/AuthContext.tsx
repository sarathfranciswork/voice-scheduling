import { createContext, useContext, useState, useCallback, useRef, type ReactNode } from 'react';

interface UserProfile {
  firstName: string;
  lastName: string;
  email: string;
  dateOfBirth: string;
}

interface AuthState {
  isAuthenticated: boolean;
  isLoggingIn: boolean;
  user: UserProfile | null;
  error: string | null;
}

interface AuthContextType extends AuthState {
  startLogin: () => Promise<void>;
  logout: () => Promise<void>;
  cancelLogin: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

const API_BASE = '';

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    isAuthenticated: false,
    isLoggingIn: false,
    user: null,
    error: null,
  });

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelledRef = useRef(false);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startLogin = useCallback(async () => {
    setState(s => ({ ...s, isLoggingIn: true, error: null }));
    cancelledRef.current = false;

    try {
      const res = await fetch(`${API_BASE}/api/auth/start-login`, { method: 'POST' });
      const data = await res.json();

      if (data.status !== 'browser_opened') {
        setState(s => ({ ...s, isLoggingIn: false, error: data.message || 'Failed to open login' }));
        return;
      }

      pollRef.current = setInterval(async () => {
        if (cancelledRef.current) {
          stopPolling();
          return;
        }

        try {
          const pollRes = await fetch(`${API_BASE}/api/auth/status`);
          const pollData = await pollRes.json();

          if (pollData.status === 'authenticated') {
            stopPolling();
            setState({
              isAuthenticated: true,
              isLoggingIn: false,
              user: pollData.profile || null,
              error: null,
            });
          } else if (pollData.status === 'error') {
            stopPolling();
            setState(s => ({
              ...s,
              isLoggingIn: false,
              error: pollData.message || 'Login failed. Please try again.',
            }));
          }
        } catch {
          // Network error -- keep polling
        }
      }, 3000);
    } catch (e) {
      setState(s => ({ ...s, isLoggingIn: false, error: String(e) }));
    }
  }, [stopPolling]);

  const cancelLogin = useCallback(() => {
    cancelledRef.current = true;
    stopPolling();
    setState(s => ({ ...s, isLoggingIn: false, error: null }));
    // Clean up backend browser session
    fetch(`${API_BASE}/api/auth/logout`, { method: 'POST' }).catch(() => {});
  }, [stopPolling]);

  const logout = useCallback(async () => {
    try {
      await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST' });
    } catch {
      // Best effort
    }
    setState({ isAuthenticated: false, isLoggingIn: false, user: null, error: null });
  }, []);

  return (
    <AuthContext.Provider value={{ ...state, startLogin, logout, cancelLogin }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
