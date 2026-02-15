const GALLERY_STORAGE_KEY = "syn_splatt_gallery";

export interface SavedGalleryItem {
  id: string;
  name: string;
  plyDataBase64: string;
  createdAt: number;
}

export function getSavedGalleryItems(): SavedGalleryItem[] {
  try {
    const raw = localStorage.getItem(GALLERY_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function uint8ArrayToBase64(bytes: Uint8Array): string {
  const chunkSize = 8192;
  let binary = "";
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
  }
  return btoa(binary);
}

export function saveGalleryItem(
  name: string,
  plyData: Uint8Array
): SavedGalleryItem {
  const base64 = uint8ArrayToBase64(plyData);
  const item: SavedGalleryItem = {
    id: crypto.randomUUID(),
    name,
    plyDataBase64: base64,
    createdAt: Date.now(),
  };
  const items = getSavedGalleryItems();
  items.unshift(item);
  localStorage.setItem(GALLERY_STORAGE_KEY, JSON.stringify(items));
  return item;
}

export function removeSavedGalleryItem(id: string): void {
  const items = getSavedGalleryItems().filter((i) => i.id !== id);
  localStorage.setItem(GALLERY_STORAGE_KEY, JSON.stringify(items));
}
