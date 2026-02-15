import { useState } from "react";
import Gallery from "./Gallery";
import GalleryModal from "./GalleryModal";
import TabSelector from "./TabSelector";
import PromptInput from "./PromptInput";
import GenerateButton from "./GenerateButton";
import type { Category } from "../App";

interface HomePageProps {
  onGenerate: (prompt: string, category: Category, files: File[]) => void;
}

type PageView = "create" | "gallery";

const SIDEBAR_EXAMPLES = [
  { name: "Auditorium", previewImage: "/previews/Auditorium.png", plyPath: "/models/Auditorium.ply" },
  { name: "Chips", previewImage: "/previews/Chips.png", plyPath: "/models/Chips.ply" },
  { name: "Timer", previewImage: "/previews/Timer.png", plyPath: "/models/Timer.ply" },
];

export default function HomePage({ onGenerate }: HomePageProps) {
  const [view, setView] = useState<PageView>("create");
  const [category, setCategory] = useState<Category>("autonomous");
  const [prompt, setPrompt] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [debugMode, setDebugMode] = useState(false);
  const [selectedExample, setSelectedExample] = useState<typeof SIDEBAR_EXAMPLES[number] | null>(null);

  const handleGenerate = () => {
    onGenerate(prompt, category, uploadFiles);
  };

  return (
    <div className="home-page">
      {/* Top Navigation */}
      <div className="home-nav">
        <button
          className={`home-nav-btn${view === "create" ? " active" : ""}`}
          onClick={() => setView("create")}
        >
          Create New
        </button>
        <button
          className={`home-nav-btn${view === "gallery" ? " active" : ""}`}
          onClick={() => setView("gallery")}
        >
          Gallery
        </button>
      </div>

      {/* Create New View */}
      {view === "create" && (
        <div className="create-view">
          <div className="create-content">
            <div className="create-header">
              <h1>syn_splatt</h1>
              <p>Generate realistic training environments for autonomous vehicles and humanoid robots.</p>
            </div>

            <TabSelector category={category} onSelect={setCategory} />

            <PromptInput
              category={category}
              prompt={prompt}
              onPromptChange={setPrompt}
              files={uploadFiles}
              onFilesChange={setUploadFiles}
            />

            <GenerateButton
              generating={false}
              disabled={uploadFiles.length === 0 && !prompt.trim()}
              onClick={handleGenerate}
            />

            <button
              className={`create-debug-toggle${debugMode ? " active" : ""}`}
              onClick={() => setDebugMode((d) => !d)}
            >
              Debug
            </button>
          </div>

          {/* Small example previews on the side */}
          <div className="create-examples">
            <div className="create-examples-header">Example Outputs</div>
            <div className="create-examples-grid">
              {SIDEBAR_EXAMPLES.map((item) => (
                <div
                  key={item.name}
                  className="create-example-item clickable"
                  onClick={() => setSelectedExample(item)}
                >
                  <img src={item.previewImage} alt={item.name} />
                  <div className="create-example-overlay">
                    <span className="create-example-name">{item.name}</span>
                  </div>
                </div>
              ))}
            </div>
            <button className="create-view-all" onClick={() => setView("gallery")}>
              View all examples →
            </button>
          </div>
        </div>
      )}

      {/* Gallery View */}
      {view === "gallery" && <Gallery />}

      {/* Modal for sidebar example clicks */}
      {selectedExample && (
        <GalleryModal
          item={selectedExample}
          onClose={() => setSelectedExample(null)}
        />
      )}
    </div>
  );
}
