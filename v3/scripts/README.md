# Preview Generator for PLY Files

Generates looping MP4 preview videos from PLY/Gaussian Splat files using headless browser automation.

## Prerequisites

1. **Node.js 16+** (for Puppeteer)
2. **ffmpeg** (for video encoding)

Install ffmpeg:
```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows (with Chocolatey)
choco install ffmpeg
```

## Installation

```bash
cd scripts
npm install
```

This will install Puppeteer and its dependencies (including Chromium).

## Usage

### Single File

```bash
node generate-preview.js <path-to-ply> [output-name]
```

**Example:**
```bash
node generate-preview.js ../runs/run-abc123/gaussians.ply scene1
```

This creates: `../frontend/public/previews/scene1.mp4`

### Batch Processing (Multiple Files)

```bash
node batch-generate-previews.js <ply-1> <ply-2> <ply-3> ...
```

**Examples:**
```bash
# Process specific files
node batch-generate-previews.js file1.ply file2.ply file3.ply

# Process all PLY files in a directory
node batch-generate-previews.js ../runs/*/gaussians.ply

# Process from a list
node batch-generate-previews.js $(cat ply-list.txt)
```

## Configuration

Edit `CONFIG` in `generate-preview.js`:

```javascript
const CONFIG = {
  width: 512,          // Video width
  height: 512,         // Video height
  fps: 30,             // Frames per second
  duration: 3,         // Video duration in seconds
  rotationSpeed: Math.PI / 2,  // Rotation speed (radians/sec)
};
```

## Output

- Preview videos are saved to: `../frontend/public/previews/`
- Frames are temporarily saved during processing and cleaned up automatically
- Videos are encoded as H.264 MP4 (web-compatible)

## How It Works

1. Loads PLY file and converts to base64
2. Launches headless Chrome with Puppeteer
3. Renders the SplatViewer using Three.js and Spark
4. Rotates camera and captures frames
5. Uses ffmpeg to compile frames into MP4
6. Cleans up temporary frames

## Troubleshooting

**"PLY file not found"**
- Check the file path is correct and the file exists

**"ffmpeg not found"**
- Install ffmpeg (see Prerequisites)

**"Timeout waiting for viewerReady"**
- PLY file may be too large or corrupted
- Try increasing timeout in `page.waitForFunction()`

**Low quality previews**
- Increase `width` and `height` in CONFIG
- Decrease `crf` value in ffmpeg command (lower = better quality, larger file)

## Next Steps

After generating previews, use them in the Gallery component:

```jsx
<video loop autoPlay muted>
  <source src="/previews/scene1.mp4" type="video/mp4" />
</video>
```
