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

interface GalleryProps {
  onGenerate: () => void;
  generateUI: React.ReactNode;
}

export default function Gallery({ onGenerate, generateUI }: GalleryProps) {
  const [selectedItem, setSelectedItem] = useState<GalleryItem | null>(null);

  // Create 3x3 grid with center being the generate UI
  const gridItems = [
    GALLERY_ITEMS[0], // top-left
    GALLERY_ITEMS[1], // top-center
    GALLERY_ITEMS[2], // top-right
    GALLERY_ITEMS[3], // middle-left
    null,              // middle-center (input box)
    GALLERY_ITEMS[4], // middle-right
    null,              // bottom-left (empty for now)
    null,              // bottom-center (empty for now)
    null,              // bottom-right (empty for now)
  ];

  return (
    <>
      <div className="gallery-container">
        <div className="gallery-grid">
          {gridItems.map((item, index) => {
            // Center cell (index 4) is the generate UI
            if (index === 4) {
              return (
                <div key="center" className="gallery-cell gallery-cell-center">
                  {generateUI}
                </div>
              );
            }

            // Empty cells
            if (!item) {
              return (
                <div key={`empty-${index}`} className="gallery-cell gallery-cell-empty">
                  <div className="coming-soon">More coming soon...</div>
                </div>
              );
            }

            // Gallery item cells
            return (
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
            );
          })}
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
