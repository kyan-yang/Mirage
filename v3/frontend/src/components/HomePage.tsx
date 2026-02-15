import { useState } from "react";
import Gallery from "./Gallery";
import TabSelector from "./TabSelector";
import PromptInput from "./PromptInput";
import GenerateButton from "./GenerateButton";
import type { Category } from "../App";

interface HomePageProps {
  onGenerate: (prompt: string, category: Category, files: File[]) => void;
}

export default function HomePage({ onGenerate }: HomePageProps) {
  const [category, setCategory] = useState<Category>("autonomous");
  const [prompt, setPrompt] = useState("");
  const [uploadFiles, setUploadFiles] = useState<File[]>([]);
  const [debugMode, setDebugMode] = useState(false);

  const handleGenerate = () => {
    onGenerate(prompt, category, uploadFiles);
  };

  const generateUI = (
    <div className="home-generate-box">
      <div className="home-header">
        <h1>Synthetic Training Environments</h1>
        <p>Generate realistic training environments for autonomous vehicles and humanoid robots.</p>
      </div>

      <div className="home-controls">
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
      </div>

      <button
        className={`home-debug-toggle${debugMode ? " active" : ""}`}
        onClick={() => setDebugMode((d) => !d)}
      >
        Debug
      </button>

      <div className="home-hint">
        Click any preview to explore in 3D
      </div>
    </div>
  );

  return <Gallery onGenerate={handleGenerate} generateUI={generateUI} />;
}
