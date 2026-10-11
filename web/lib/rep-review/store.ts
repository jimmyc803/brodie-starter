import type { PoseTrack } from "./pose-types";

const DB_NAME = "rep-review";
const POSES = "poses";
const CLIPS = "clips";

type StoredClip = { name: string; type: string; blob: Blob; addedAt: number };

function openDb(): Promise<IDBDatabase | null> {
  return new Promise((resolve) => {
    try {
      if (typeof indexedDB === "undefined") return resolve(null);
      const req = indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(POSES)) db.createObjectStore(POSES);
        if (!db.objectStoreNames.contains(CLIPS)) db.createObjectStore(CLIPS);
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

// Runs one request against a store; resolves fallback when storage is unavailable or fails.
async function run<T>(
  store: string,
  mode: IDBTransactionMode,
  make: (s: IDBObjectStore) => IDBRequest,
  fallback: T,
): Promise<T> {
  const db = await openDb();
  if (!db) return fallback;
  return new Promise<T>((resolve) => {
    try {
      const tx = db.transaction(store, mode);
      const req = make(tx.objectStore(store));
      let result: unknown = fallback;
      req.onsuccess = () => {
        result = req.result === undefined ? fallback : req.result;
      };
      tx.oncomplete = () => {
        db.close();
        resolve(result as T);
      };
      tx.onerror = tx.onabort = () => {
        db.close();
        resolve(fallback);
      };
    } catch {
      db.close();
      resolve(fallback);
    }
  });
}

export async function getPose(key: string): Promise<PoseTrack | null> {
  return run<PoseTrack | null>(POSES, "readonly", (s) => s.get(key), null);
}

export async function putPose(key: string, track: PoseTrack): Promise<void> {
  await run<null>(POSES, "readwrite", (s) => s.put(track, key), null);
}

export async function getUploadedClip(id: string): Promise<StoredClip | null> {
  return run<StoredClip | null>(CLIPS, "readonly", (s) => s.get(id), null);
}

export async function putUploadedClip(id: string, file: File): Promise<void> {
  const clip: StoredClip = { name: file.name, type: file.type, blob: file, addedAt: Date.now() };
  await run<null>(CLIPS, "readwrite", (s) => s.put(clip, id), null);
}

export async function deleteUploadedClip(id: string): Promise<void> {
  await run<null>(CLIPS, "readwrite", (s) => s.delete(id), null);
}

export async function listUploadedClipIds(): Promise<string[]> {
  const keys = await run<IDBValidKey[]>(CLIPS, "readonly", (s) => s.getAllKeys(), []);
  return keys.map(String);
}
