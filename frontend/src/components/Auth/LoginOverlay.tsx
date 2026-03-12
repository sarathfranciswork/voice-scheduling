import { useAuth } from '../../contexts/AuthContext';

export default function LoginOverlay() {
  const { isLoggingIn, error, cancelLogin } = useAuth();

  if (!isLoggingIn) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="bg-white rounded-2xl shadow-2xl p-8 max-w-md w-full mx-4 text-center">
        {/* Spinner */}
        <div className="flex justify-center mb-5">
          <div className="w-12 h-12 border-4 border-cvs-primary-200 border-t-cvs-primary rounded-full animate-spin" />
        </div>

        <h2 className="text-xl font-semibold text-cvs-text mb-2">
          Complete login in the CVS window
        </h2>
        <p className="text-sm text-cvs-text-secondary mb-1">
          A browser window has opened with the CVS login page.
        </p>
        <p className="text-sm text-cvs-text-secondary mb-6">
          Sign in using your preferred method (code or password), then return here.
        </p>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">
            {error}
          </div>
        )}

        <button
          onClick={cancelLogin}
          className="px-5 py-2 rounded-lg border border-cvs-border text-cvs-text-secondary hover:bg-cvs-surface transition-colors text-sm font-medium"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
