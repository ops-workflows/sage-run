import React from 'react';
import ReactDOM from 'react-dom/client';
import '@/app/globals.css';
import { initMockAdapter } from './mock-adapter';
import { App } from './app';

initMockAdapter();

const rootElement = document.getElementById('root');
if (rootElement) {
  ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
