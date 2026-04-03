import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import '../../../../caden-base.css';
import './App.css';

// Immediate DOM probe â€” visible before React mounts.
// If this appears the JS bundle is executing.
const probe = document.createElement('div');
probe.id = 'pm-probe';
probe.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:9999;background:rgb(var(--c-urgency-high));color:#fff;font:13px monospace;padding:4px 8px';
probe.textContent = 'PedalManifest JS loadingâ€¦';
document.body.appendChild(probe);

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: 20, fontFamily: 'monospace', fontSize: 13, color: 'rgb(var(--c-urgency-high))', background: 'rgb(var(--c-surface))', height: '100vh' }}>
          <div style={{ marginBottom: 8, color: 'rgb(var(--c-text))' }}>PedalManifest render error:</div>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{String(this.state.error)}</pre>
          {this.state.error.stack && (
            <pre style={{ marginTop: 12, color: 'rgb(var(--c-text-muted))', whiteSpace: 'pre-wrap', fontSize: 11 }}>{this.state.error.stack}</pre>
          )}
        </div>
      );
    }
    return this.props.children;
  }
}

try {
  const root = ReactDOM.createRoot(document.getElementById('root'));
  root.render(
    <React.StrictMode>
      <ErrorBoundary>
        <App />
      </ErrorBoundary>
    </React.StrictMode>
  );
  // Remove the probe after React mounts â€” if this runs, React is working
  setTimeout(() => {
    const p = document.getElementById('pm-probe');
    if (p) p.remove();
  }, 500);
} catch (err) {
  const p = document.getElementById('pm-probe');
  if (p) p.textContent = 'PedalManifest FATAL: ' + String(err);
}
