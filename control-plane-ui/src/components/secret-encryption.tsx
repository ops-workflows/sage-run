'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { encryptSecret } from '@/lib/secret-encryption';

interface EncryptionKey {
  public_key: string;
  environment: string;
}

export function SecretEncryption() {
  const [key, setKey] = useState<EncryptionKey | null>(null);
  const [plaintext, setPlaintext] = useState('');
  const [encrypted, setEncrypted] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    apiFetch<EncryptionKey>('/api/platform/encryption-key', {
      cache: 'no-store',
    })
      .then(setKey)
      .catch((err: Error) => setError(err.message));
  }, []);

  async function encrypt(event: React.FormEvent) {
    event.preventDefault();
    if (!key) return;
    setBusy(true);
    setError(null);
    setEncrypted('');
    setCopied(false);
    try {
      // Re-read the active recipient in case a deployment changed environments or keys.
      const active = await apiFetch<EncryptionKey>(
        '/api/platform/encryption-key',
        {
          cache: 'no-store',
        },
      );
      setKey(active);
      setEncrypted(await encryptSecret(plaintext, active.public_key));
      setPlaintext('');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Encryption failed.');
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    setError(null);
    try {
      await navigator.clipboard.writeText(encrypted);
      setCopied(true);
    } catch {
      setError(
        'Clipboard unavailable. Select and copy the encrypted value below.',
      );
    }
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h2 className="font-display text-2xl text-[var(--color-text-primary)]">
          Encrypt a secret
        </h2>
        <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
          Encryption happens in this browser. The secret is not sent to the
          server or saved. Copy the encrypted value into your workflow
          repository, then commit and deploy it yourself. No pull request is
          created.
        </p>
      </div>
      {key && (
        <div className="rounded-card border border-ops-border bg-ops-surface p-4 text-sm">
          <p>
            Active environment: <strong>{key.environment}</strong>
          </p>
          <p className="mt-2 break-all font-mono">{key.public_key}</p>
          <p className="mt-2 text-[var(--color-text-secondary)]">
            Confirm the environment and recipient before encrypting. Use a
            trusted HTTPS connection or localhost to load this tool.
          </p>
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-red-500">
          {error}
        </p>
      )}
      <form onSubmit={encrypt} className="space-y-3">
        <label htmlFor="secret-value" className="block text-sm font-medium">
          Secret value
        </label>
        <textarea
          id="secret-value"
          value={plaintext}
          onChange={(event) => {
            setPlaintext(event.target.value);
            setEncrypted('');
            setCopied(false);
          }}
          disabled={!key || busy}
          autoComplete="off"
          autoCapitalize="off"
          spellCheck={false}
          rows={4}
          required
          className="w-full rounded-btn border border-ops-border bg-ops-surface p-3 font-mono text-sm"
        />
        <button
          type="submit"
          disabled={!key || !plaintext || busy}
          className="rounded-btn bg-[var(--color-accent)] px-4 py-2 text-sm text-white disabled:opacity-50"
        >
          {busy ? 'Encrypting...' : 'Encrypt'}
        </button>
      </form>
      {encrypted && (
        <div className="space-y-3">
          <label
            htmlFor="encrypted-value"
            className="block text-sm font-medium"
          >
            Encrypted value
          </label>
          <textarea
            id="encrypted-value"
            readOnly
            value={encrypted}
            rows={5}
            onFocus={(event) => event.target.select()}
            className="w-full rounded-btn border border-ops-border bg-ops-surface p-3 font-mono text-sm"
          />
          <button
            type="button"
            onClick={copy}
            className="rounded-btn border border-ops-border px-4 py-2 text-sm"
          >
            {copied ? 'Copied' : 'Copy encrypted value'}
          </button>
        </div>
      )}
    </div>
  );
}
