import type { Category } from "../App";

interface PromptInputProps {
  category: Category;
  prompt: string;
  onPromptChange: (value: string) => void;
}

const EXAMPLES: Record<Category, { label: string; prompt: string }[]> = {
  autonomous: [
    { label: "Snowy road", prompt: "snowy road with ice patches" },
    { label: "Fallen tree", prompt: "road with fallen tree blocking traffic" },
    { label: "Flooded street", prompt: "flooded suburban street with abandoned cars" },
    { label: "Construction", prompt: "construction zone on highway with cones and barriers" },
    { label: "Rain at night", prompt: "city intersection at night with heavy rain" },
    { label: "Heavy fog", prompt: "foggy mountain road with reduced visibility" },
    { label: "Accident scene", prompt: "highway with overturned truck and debris" },
    { label: "Narrow bridge", prompt: "narrow bridge with oncoming traffic" },
  ],
  humanoid: [
    { label: "Dirty dishes", prompt: "pile of dirty dishes in kitchen sink" },
    { label: "Laundry pile", prompt: "laundry basket full of clothes on bed" },
    { label: "Toy mess", prompt: "cluttered living room with toys scattered on floor" },
    { label: "Grocery spill", prompt: "kitchen counter with spilled groceries and bags" },
    { label: "Messy bed", prompt: "unmade bed with tangled sheets and pillows" },
    { label: "Meal cleanup", prompt: "dining table with plates, cups, and food scraps" },
    { label: "Bathroom mess", prompt: "bathroom with wet towels on floor" },
    { label: "Desk clutter", prompt: "workspace desk with papers and cables tangled" },
  ],
};

export default function PromptInput({
  category,
  prompt,
  onPromptChange,
}: PromptInputProps) {
  const examples = EXAMPLES[category];
  const placeholder =
    category === "autonomous"
      ? "Describe a driving scenario..."
      : "Describe a household scenario...";

  return (
    <div className="input-area">
      <textarea
        placeholder={placeholder}
        rows={3}
        value={prompt}
        onChange={(e) => onPromptChange(e.target.value)}
      />
      <div className="examples">
        {examples.map((ex) => (
          <button key={ex.label} onClick={() => onPromptChange(ex.prompt)}>
            {ex.label}
          </button>
        ))}
      </div>
    </div>
  );
}
