import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { Decrypter, generateIdentity, identityToRecipient } from 'age-encryption';
import ts from 'typescript';

const source = readFileSync(new URL('../src/lib/secret-encryption.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText.replace("'age-encryption'", JSON.stringify(import.meta.resolve('age-encryption')));
const { encryptSecret } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('encrypts multiline Unicode without trimming into the platform ENC format', async () => {
  const identity = await generateIdentity();
  const recipient = await identityToRecipient(identity);
  const plaintext = '  token\npässword 🔑\n';
  const encrypted = await encryptSecret(plaintext, recipient);
  assert.match(encrypted, /^ENC\[age,[A-Za-z0-9+/=]+\]$/);
  const decrypter = new Decrypter();
  decrypter.addIdentity(identity);
  assert.equal(await decrypter.decrypt(Buffer.from(encrypted.slice(8, -1), 'base64'), 'text'), plaintext);
  assert.notEqual(await encryptSecret(plaintext, recipient), encrypted);
});

test('rejects empty secrets and invalid recipients explicitly', async () => {
  await assert.rejects(encryptSecret('', 'invalid'), /Enter a secret/);
  await assert.rejects(encryptSecret('not-sent-to-server', 'invalid'));
});
