// PWA-02 — local storage for the offline queue (IndexedDB, no dependency).
//
// Three object stores in one database:
//   meta  — the device id (a UUID made once; survives logout, which clears localStorage)
//   keys  — one AES-GCM CryptoKey per owner (tenant:user), NON-EXTRACTABLE
//   queue — the queued records; only routing fields are plaintext, the envelope with the
//           payload is ciphertext (see crypto.js)
// A memory implementation with the same interface is used by the unit tests.

export const DB_NAME = "bw-offline";
const DB_VERSION = 1;
const STORES = ["meta", "keys", "queue"];

function req(r) {
  return new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}

export function idbStore(indexedDB = typeof window !== "undefined" ? window.indexedDB : undefined) {
  let dbp = null;
  const open = () => {
    if (!indexedDB) return Promise.reject(new Error("IndexedDB unavailable"));
    if (!dbp) {
      const r = indexedDB.open(DB_NAME, DB_VERSION);
      r.onupgradeneeded = () => {
        const db = r.result;
        STORES.forEach((s) => {
          if (!db.objectStoreNames.contains(s)) db.createObjectStore(s);
        });
      };
      dbp = req(r).then((db) => {
        // another tab deletes the database (a blocked device): let go at once
        db.onversionchange = () => { db.close(); dbp = null; };
        return db;
      });
    }
    return dbp;
  };
  const tx = async (store, mode, fn) => {
    const db = await open();
    const t = db.transaction(store, mode);
    const result = await fn(t.objectStore(store));
    await new Promise((resolve, reject) => {
      t.oncomplete = resolve;
      t.onerror = () => reject(t.error);
      t.onabort = () => reject(t.error);
    });
    return result;
  };
  return {
    get: (store, key) => tx(store, "readonly", (s) => req(s.get(key))),
    put: (store, key, value) => tx(store, "readwrite", (s) => req(s.put(value, key))),
    del: (store, key) => tx(store, "readwrite", (s) => req(s.delete(key))),
    all: (store) => tx(store, "readonly", async (s) => {
      const keys = await req(s.getAllKeys());
      const values = await req(s.getAll());
      return keys.map((k, i) => [k, values[i]]);
    }),
    // R61-6: a blocked device wipes everything local. The stores are emptied first, so
    // nothing is left even while another open tab still holds the database; the delete
    // itself then completes as soon as that tab lets go (onversionchange above).
    destroy: async () => {
      try {
        const db = await open();
        const t = db.transaction(STORES, "readwrite");
        STORES.forEach((s) => t.objectStore(s).clear());
        await new Promise((resolve) => { t.oncomplete = resolve; t.onerror = resolve; t.onabort = resolve; });
        db.close();
      } catch { /* nothing to clear */ }
      dbp = null;
      if (indexedDB) {
        await new Promise((resolve) => {
          const r = indexedDB.deleteDatabase(DB_NAME);
          r.onsuccess = resolve;
          r.onerror = resolve;
          r.onblocked = resolve; // finishes later; the data is already gone
        });
      }
    },
  };
}

export function memoryStore() {
  const data = Object.fromEntries(STORES.map((s) => [s, new Map()]));
  return {
    get: async (store, key) => data[store].get(key),
    put: async (store, key, value) => { data[store].set(key, value); },
    del: async (store, key) => { data[store].delete(key); },
    all: async (store) => [...data[store].entries()],
    destroy: async () => { STORES.forEach((s) => data[s].clear()); },
    _data: data,
  };
}
