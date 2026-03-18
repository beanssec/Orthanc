import { Component, ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  /** Optional endpoint to POST errors to (e.g. /api/v1/health/error-report) */
  reportUrl?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: import('react').ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null, errorInfo: null };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: import('react').ErrorInfo) {
    console.error('[ErrorBoundary] Caught render error:', error, info);
    this.setState({ errorInfo: info });

    // Optional: report to backend (best-effort, non-blocking)
    if (this.props.reportUrl) {
      try {
        fetch(this.props.reportUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            message: error.message,
            stack: error.stack?.slice(0, 2000),
            componentStack: info.componentStack?.slice(0, 2000),
            timestamp: new Date().toISOString(),
          }),
        }).catch(() => {
          // Silently swallow — error reporting must never throw
        });
      } catch {
        // noop
      }
    }
  }

  private handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="error-boundary">
          <div className="error-boundary__icon">⚠️</div>
          <h3 className="error-boundary__title">Something went wrong</h3>
          <p className="error-boundary__message">
            {this.state.error?.message || 'An unexpected error occurred.'}
          </p>
          {process.env.NODE_ENV === 'development' && this.state.errorInfo && (
            <details className="error-boundary__details">
              <summary>Stack trace</summary>
              <pre className="error-boundary__stack">
                {this.state.error?.stack}
                {'\n\nComponent Stack:'}
                {this.state.errorInfo.componentStack}
              </pre>
            </details>
          )}
          <button
            className="btn btn-primary btn-sm"
            onClick={this.handleReset}
          >
            Try Again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
