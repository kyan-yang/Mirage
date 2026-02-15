import type { Category } from "../App";

interface TabSelectorProps {
  category: Category;
  onSelect: (category: Category) => void;
}

const TABS: { id: Category; label: string }[] = [
  { id: "autonomous", label: "Autonomous Driving" },
  { id: "humanoid", label: "Humanoid Robots" },
];

export default function TabSelector({ category, onSelect }: TabSelectorProps) {
  return (
    <div className="tabs">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          className={`tab${category === tab.id ? " active" : ""}`}
          onClick={() => onSelect(tab.id)}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}
