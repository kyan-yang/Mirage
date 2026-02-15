import type { GalleryItem } from "./components/Gallery";

const BLOB_URL = import.meta.env.VITE_BLOB_URL || "";

function modelUrl(filename: string): string {
  return BLOB_URL ? `${BLOB_URL}/models/${filename}` : `/models/${filename}`;
}

export const STATIC_MODELS: GalleryItem[] = [
  { name: "Auditorium", previewImage: "/previews/Auditorium.png", plyPath: modelUrl("Auditorium.ply") },
  { name: "Chips", previewImage: "/previews/Chips.png", plyPath: modelUrl("Chips.ply") },
  { name: "Timer", previewImage: "/previews/Timer.png", plyPath: modelUrl("Timer.ply") },
  { name: "Tree", previewImage: "/previews/Tree.png", plyPath: modelUrl("Tree.ply") },
  { name: "TreeHacks", previewImage: "/previews/TreeHacks.png", plyPath: modelUrl("Treehacks.ply") },
  { name: "Mess", previewImage: "/previews/Mess.png", plyPath: modelUrl("Mess.ply") },
];
