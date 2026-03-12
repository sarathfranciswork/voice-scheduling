import { useTheme } from '../../contexts/ThemeContext';
import { useAuth } from '../../contexts/AuthContext';
import cvsHeart from '../../assets/cvs-heart.png';

interface HeaderProps {
  onToggleSidebar: () => void;
  sidebarOpen: boolean;
}

export default function Header({ onToggleSidebar, sidebarOpen }: HeaderProps) {
  const { theme, toggleTheme } = useTheme();
  const { isAuthenticated, isLoggingIn, user, startLogin, logout } = useAuth();

  const initials = user
    ? `${user.firstName?.[0] || ''}${user.lastName?.[0] || ''}`.toUpperCase()
    : '';

  return (
    <header className="h-14 bg-white border-b border-cvs-border flex items-center px-4 gap-3 shrink-0 shadow-sm">
      {/* Hamburger for mobile */}
      <button
        onClick={onToggleSidebar}
        className="lg:hidden p-1.5 rounded-lg hover:bg-cvs-surface transition-colors"
        aria-label={sidebarOpen ? 'Close sidebar' : 'Open sidebar'}
      >
        <svg className="w-5 h-5 text-cvs-text" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          {sidebarOpen ? (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          ) : (
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          )}
        </svg>
      </button>

      {/* Logo + Title */}
      <div className="flex items-center gap-2.5">
        <img src={cvsHeart} alt="CVS Health" className="h-8 w-8 object-contain" />
        <div>
          <h1 className="text-base font-semibold text-cvs-text leading-tight">
            CVS Health
          </h1>
          <p className="text-[11px] text-cvs-text-secondary leading-tight">
            Vaccine Scheduling Assistant
          </p>
        </div>
      </div>

      <div className="flex-1" />

      {/* Auth section */}
      <div className="flex items-center gap-2.5">
        {isAuthenticated ? (
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-full bg-cvs-primary flex items-center justify-center">
              <span className="text-white text-xs font-semibold">
                {initials || (
                  <svg className="w-3.5 h-3.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                )}
              </span>
            </div>
            <span className="text-xs font-medium text-cvs-text hidden sm:inline">
              {user?.firstName || 'Signed in'}
            </span>
            <button
              onClick={logout}
              className="text-xs text-cvs-text-secondary hover:text-cvs-primary transition-colors"
              title="Sign out"
            >
              Sign out
            </button>
          </div>
        ) : (
          <button
            onClick={startLogin}
            disabled={isLoggingIn}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-cvs-primary text-white hover:bg-cvs-primary-hover transition-colors text-xs font-medium disabled:opacity-60"
          >
            {isLoggingIn ? (
              <>
                <div className="w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Logging in...
              </>
            ) : (
              <>
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
                Login via CVS
              </>
            )}
          </button>
        )}

        {/* Theme toggle */}
        <div className="flex items-center gap-1.5">
          <button
            onClick={toggleTheme}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-full border border-cvs-border hover:bg-cvs-surface transition-colors text-xs font-medium"
            title={`Switch to CVS ${theme === 'red' ? 'Blue' : 'Red'} theme`}
          >
            <span
              className="w-3 h-3 rounded-full border border-gray-200"
              style={{
                backgroundColor: theme === 'red' ? '#CC0000' : '#17447C',
              }}
            />
            <span className="hidden sm:inline">CVS {theme === 'red' ? 'Red' : 'Blue'}</span>
          </button>
        </div>
      </div>
    </header>
  );
}
