// PWA-02 — encryption of queued records (R61-5, PWA-02 §4).
//
// * AES-GCM 256 (WebCrypto), a fresh 96-bit IV per record.
// * One key per OWNER = tenant + user. The key is generated NON-EXTRACTABLE and kept as a
//   CryptoKey object in IndexedDB: script can use it but never read its bytes, and another
//   user on the same phone gets another key, so they can neither list nor read the first
//   user's records.
// * The owner string is bound into every ciphertext as additional authenticated data, so a
//   record cannot be moved from one owner to another.

// created on use: some test environments have no TextEncoder global at import time
const enc = { encode: (s) => new TextEncoder().encode(s) };
const dec = { decode: (b) => new TextDecoder().decode(b) };

export const ownerOf = (tenantId, userId) => `${tenantId}:${userId}`;

export async function ownerKey(store, owner, subtle = globalThis.crypto && globalThis.crypto.subtle) {
  if (!subtle) throw new Error("WebCrypto unavailable");
  const existing = await store.get("keys", owner);
  if (existing) return existing;
  const key = await subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  await store.put("keys", owner, key);
  return key;
}

const toB64 = (buf) => {
  const bytes = new Uint8Array(buf);
  let s = "";
  for (let i = 0; i < bytes.length; i += 1) s += String.fromCharCode(bytes[i]);
  return btoa(s);
};
const fromB64 = (b64) => Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));

export async function seal(key, owner, value, subtle = globalThis.crypto.subtle,
  getRandomValues = (a) => globalThis.crypto.getRandomValues(a)) {
  const iv = getRandomValues(new Uint8Array(12));
  const ct = await subtle.encrypt({ name: "AES-GCM", iv, additionalData: enc.encode(owner) }, key,
    enc.encode(JSON.stringify(value)));
  return { iv: toB64(iv), ct: toB64(ct) };
}

export async function open(key, owner, sealed, subtle = globalThis.crypto.subtle) {
  const pt = await subtle.decrypt({ name: "AES-GCM", iv: fromB64(sealed.iv), additionalData: enc.encode(owner) },
    key, fromB64(sealed.ct));
  return JSON.parse(dec.decode(pt));
}

// SHA-256 of a file / blob, computed on the phone (FLOW-037 L192: the original stays until
// the server confirms the same checksum).
export async function sha256Hex(data, subtle = globalThis.crypto.subtle) {
  const buf = data instanceof ArrayBuffer ? data
    : (typeof data.arrayBuffer === "function" ? await data.arrayBuffer() : await new Response(data).arrayBuffer());
  const digest = await subtle.digest("SHA-256", buf);
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
}
