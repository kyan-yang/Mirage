import { useState } from "react";
import GalleryModal from "./GalleryModal";

interface GalleryItem {
  name: string;
  previewImage: string;
  plyPath: string;
}

const GALLERY_ITEMS: GalleryItem[] = [
  { name: "Auditorium", previewImage: "/previews/Auditorium.png", plyPath: "/models/Auditorium.ply" },
  { name: "Chips", previewImage: "/previews/Chips.png", plyPath: "/models/Chips.ply" },
  { name: "Timer", previewImage: "/previews/Timer.png", plyPath: "/models/Timer.ply" },
  { name: "Tree", previewImage: "/previews/Tree.png", plyPath: "/models/Tree.ply" },
  { name: "TreeHacks", previewImage: "/previews/TreeHacks.png", plyPath: "/models/Treehacks.ply" },
];

export default function Gallery() {
  const [selectedItem, setSelectedItem] = useState<GalleryItem | null>(null);

  return (
    <>
      <div className="gallery-view">
        <div className="gallery-header">
          <h2>Example Outputs</h2>
          <p>Explore our collection of generated 3D environments</p>
        </div>

        <div className="gallery-full-grid">
          {GALLERY_ITEMS.map((item) => (
            <div
              key={item.name}
              className="gallery-cell gallery-cell-item"
              onClick={() => setSelectedItem(item)}
            >
              <div className="gallery-preview">
                <img src={item.previewImage} alt={item.name} />
                <div className="gallery-overlay">
                  <span className="gallery-name">{item.name}</span>
                  <span className="gallery-action">Click to view</span>
                </div>
              </div>
            </div>
          ))}

          {/* Placeholder cells for "coming soon" */}
          {[1, 2, 3].map((i) => (
            <div key={`empty-${i}`} className="gallery-cell gallery-cell-empty">
              <div className="coming-soon">More coming soon...</div>
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
