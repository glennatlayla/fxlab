import { useContext } from 'react';

interface AuthContextType {
  isAuthenticated: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

// Re-export the hook from AuthProvider
export { useAuth } from './AuthProvider';
