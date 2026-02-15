import type { Category } from "../App";

interface PromptInputProps {
  category: Category;
  prompt: string;
  onPromptChange: (value: string) => void;
}

const EXAMPLES: Record<Category, { label: string; prompt: string }[]> = {
  autonomous: [
    { label: "Snowy road with ice patches", prompt: "snowy road with ice patches" },
    { label: "Fallen tree blocking traffic", prompt: "road with fallen tree blocking traffic" },
    { label: "Flooded street with abandoned cars", prompt: "flooded suburban street with abandoned cars" },
    { label: "Highway construction zone", prompt: "construction zone on highway with cones and barriers" },
    { label: "Rainy city intersection at night", prompt: "city intersection at night with heavy rain" },
    { label: "Foggy mountain road", prompt: "foggy mountain road with reduced visibility" },
    { label: "Overturned truck on highway", prompt: "highway with overturned truck and debris" },
    { label: "Narrow bridge with oncoming traffic", prompt: "narrow bridge with oncoming traffic" },
  ],
  humanoid: [
    { label: "Dirty dishes piled in sink", prompt: "pile of dirty dishes in kitchen sink" },
    { label: "Laundry basket on the bed", prompt: "laundry basket full of clothes on bed" },
    { label: "Toys scattered across floor", prompt: "cluttered living room with toys scattered on floor" },
    { label: "Spilled groceries on counter", prompt: "kitchen counter with spilled groceries and bags" },
    { label: "Unmade bed with tangled sheets", prompt: "unmade bed with tangled sheets and pillows" },
    { label: "Dining table after a meal", prompt: "dining table with plates, cups, and food scraps" },
    { label: "Wet towels on bathroom floor", prompt: "bathroom with wet towels on floor" },
    { label: "Cluttered desk with tangled cables", prompt: "workspace desk with papers and cables tangled" },
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
