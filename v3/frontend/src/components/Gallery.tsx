import { useState, useMemo } from "react";
import { getSavedGalleryItems } from "../galleryStore";
import GalleryModal from "./GalleryModal";

export interface GalleryItem {
  name: string;
  previewImage: string;
  plyPath?: string;
  plyDataBase64?: string;
  id?: string;
}

const STATIC_ITEMS: GalleryItem[] = [
  { name: "Auditorium", previewImage: "/previews/Auditorium.png", plyPath: "/models/Auditorium.ply" },
  { name: "Chips", previewImage: "/previews/Chips.png", plyPath: "/models/Chips.ply" },
  { name: "Timer", previewImage: "/previews/Timer.png", plyPath: "/models/Timer.ply" },
  { name: "Tree", previewImage: "/previews/Tree.png", plyPath: "/models/Tree.ply" },
  { name: "TreeHacks", previewImage: "/previews/TreeHacks.png", plyPath: "/models/Treehacks.ply" },
];

const ADD_YOURS_SLOTS = 3;

interface GalleryProps {
  onAddYours?: () => void;
}

export default function Gallery({ onAddYours }: GalleryProps) {
  const [selectedItem, setSelectedItem] = useState<GalleryItem | null>(null);

  const savedItems = useMemo(
    () =>
      getSavedGalleryItems().map((s) => ({
        id: s.id,
        name: s.name,
        previewImage: "",
        plyDataBase64: s.plyDataBase64,
      })),
    []
  );

  const allItems = [...STATIC_ITEMS, ...savedItems];

  return (
    <>
      <div className="gallery-view">
        <div className="gallery-header">
          <h2>Previously</h2>
          <p>Explore our collection of generated 3D environments</p>
        </div>

        <div className="gallery-full-grid">
          {allItems.map((item) => (
            <div
              key={item.id ?? item.name}
              className="gallery-cell gallery-cell-item"
              onClick={() => setSelectedItem(item)}
            >
              <div className="gallery-preview">
                {item.previewImage ? (
                  <img src={item.previewImage} alt={item.name} />
                ) : (
                  <div className="gallery-preview-placeholder">
                    <span className="gallery-placeholder-label">3D</span>
                  </div>
                )}
                <div className="gallery-overlay">
                  <span className="gallery-name">{item.name}</span>
                  <span className="gallery-action">Click to view</span>
                </div>
              </div>
            </div>
          ))}

          {/* "Add yours" slots — navigate to create/generate */}
          {onAddYours && Array.from({ length: ADD_YOURS_SLOTS }, (_, i) => (
            <div
              key={`add-${i}`}
              className="gallery-cell gallery-cell-add"
              onClick={onAddYours}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onAddYours();
                }
              }}
            >
              <div className="gallery-add-content">
                <span className="gallery-add-icon">+</span>
                <span className="gallery-add-text">Add yours</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {selectedItem && (
        <GalleryModal
          item={selectedItem}
          onClose={() => setSelectedItem(null)}
        />
      )}
    </>
  );
}
