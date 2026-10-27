import { Encrypter } from 'age-encryption';

export async function encryptSecret(
  plaintext: string,
  publicKey: string,
): Promise<string> {
  if (!plaintext) throw new Error('Enter a secret value.');
  const encrypter = new Encrypter();
  encrypter.addRecipient(publicKey);
  const ciphertext = await encrypter.encrypt(plaintext);
  const encoded = Array.from(ciphertext, (byte) =>
    String.fromCharCode(byte),
  ).join('');
  return `ENC[age,${btoa(encoded)}]`;
}
