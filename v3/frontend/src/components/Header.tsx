interface HeaderProps {
  debugMode: boolean;
  onToggleDebug: () => void;
}

export default function Header({ debugMode, onToggleDebug }: HeaderProps) {
  return (
    <div className="header">
      <h1>Synthetic Training Data Generator</h1>
      <p>Generate 3D scenarios for training AI models in edge-case situations</p>
      <button
        className={`debug-toggle${debugMode ? " active" : ""}`}
        onClick={onToggleDebug}
      >
        Debug
      </button>
    </div>
  );
}
