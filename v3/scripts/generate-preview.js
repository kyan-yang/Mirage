#!/usr/bin/env node

/**
 * Generate preview video clips from PLY files using headless SplatViewer
 *
 * Usage: node generate-preview.js <ply-file-path> [output-name]
 *
 * Requirements:
 * - puppeteer
 * - ffmpeg (installed on system)
 */

const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');
const { exec } = require('child_process');
const { promisify } = require('util');

const execAsync = promisify(exec);

const CONFIG = {
  width: 512,
  height: 512,
  fps: 30,
  duration: 3, // seconds
  rotationSpeed: Math.PI / 2, // radians per second (90 degrees/sec)
};

async function generatePreview(plyPath, outputName) {
  const plyFile = path.resolve(plyPath);
  if (!fs.existsSync(plyFile)) {
    throw new Error(`PLY file not found: ${plyFile}`);
  }

  const plyData = fs.readFileSync(plyFile);
  const base64Data = plyData.toString('base64');

  const outputDir = path.join(__dirname, 'preview-frames', outputName || path.basename(plyFile, '.ply'));
  const outputVideo = path.join(__dirname, '..', 'frontend', 'public', 'previews', `${outputName || path.basename(plyFile, '.ply')}.mp4`);

  // Create output directories
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }
  if (!fs.existsSync(path.dirname(outputVideo))) {
    fs.mkdirSync(path.dirname(outputVideo), { recursive: true });
  }

  console.log(`Processing: ${path.basename(plyFile)}`);
  console.log(`Frames dir: ${outputDir}`);
  console.log(`Output: ${outputVideo}`);

  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: CONFIG.width, height: CONFIG.height });

    // Create HTML with embedded SplatViewer
    const html = createViewerHTML(base64Data);
    await page.setContent(html);

    // Wait for viewer to initialize
    await page.waitForFunction(() => window.viewerReady === true, { timeout: 30000 });

    console.log('Viewer initialized, capturing frames...');

    const totalFrames = CONFIG.fps * CONFIG.duration;
    const anglePerFrame = (CONFIG.rotationSpeed * CONFIG.duration) / totalFrames;

    // Capture frames
    for (let i = 0; i < totalFrames; i++) {
      // Rotate camera
      await page.evaluate((angle) => {
        window.rotateCamera(angle);
      }, i * anglePerFrame);

      // Wait a bit for render
      await page.waitForTimeout(16); // ~60fps render time

      // Screenshot
      const framePath = path.join(outputDir, `frame-${String(i).padStart(4, '0')}.png`);
      await page.screenshot({ path: framePath, omitBackground: true });

      if (i % 10 === 0) {
        process.stdout.write(`\rCapturing: ${i + 1}/${totalFrames}`);
      }
    }

    console.log(`\n✓ Captured ${totalFrames} frames`);

    // Use ffmpeg to create video
    console.log('Creating video with ffmpeg...');
    const ffmpegCmd = `ffmpeg -y -framerate ${CONFIG.fps} -i "${outputDir}/frame-%04d.png" -c:v libx264 -pix_fmt yuv420p -preset fast -crf 23 "${outputVideo}"`;

    await execAsync(ffmpegCmd);
    console.log(`✓ Video created: ${outputVideo}`);

    // Clean up frames
    console.log('Cleaning up frames...');
    fs.rmSync(outputDir, { recursive: true, force: true });
    console.log('✓ Done!\n');

    return outputVideo;

  } finally {
    await browser.close();
  }
}

function createViewerHTML(base64PlyData) {
  return `
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    * { margin: 0; padding: 0; }
    body { overflow: hidden; background: #000; }
    #container { width: 100vw; height: 100vh; }
  </style>
</head>
<body>
  <div id="container"></div>

  <script type="importmap">
  {
    "imports": {
      "three": "https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js",
      "@sparkjsdev/spark": "https://cdn.jsdelivr.net/npm/@sparkjsdev/spark@0.1.1/dist/spark.module.js"
    }
  }
  </script>

  <script type="module">
    import * as THREE from 'three';
    import { SplatMesh } from '@sparkjsdev/spark';

    const container = document.getElementById('container');
    const canvas = document.createElement('canvas');
    canvas.width = ${CONFIG.width};
    canvas.height = ${CONFIG.height};
    container.appendChild(canvas);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(75, ${CONFIG.width} / ${CONFIG.height}, 0.01, 1000);
    camera.position.set(0, 0, 1);

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: false, alpha: true });
    renderer.setSize(${CONFIG.width}, ${CONFIG.height}, false);
    renderer.setClearColor(0x000000, 0);

    // Decode PLY data
    const base64Data = "${base64PlyData}";
    const binaryString = atob(base64Data);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }

    // Load splat
    const splatMesh = new SplatMesh({ fileBytes: bytes });
    scene.add(splatMesh);

    await splatMesh.initialized;

    // Set up lighting (optional, splats are self-lit)
    const ambientLight = new THREE.AmbientLight(0xffffff, 1);
    scene.add(ambientLight);

    // Store camera info for rotation
    const cameraDistance = 1;
    let currentAngle = 0;

    window.rotateCamera = (angle) => {
      currentAngle = angle;
      camera.position.x = Math.sin(angle) * cameraDistance;
      camera.position.z = Math.cos(angle) * cameraDistance;
      camera.position.y = 0.1;
      camera.lookAt(0, 0, 0);
      renderer.render(scene, camera);
    };

    // Initial render
    renderer.render(scene, camera);
    window.viewerReady = true;
  </script>
</body>
</html>
  `;
}

// CLI
if (require.main === module) {
  const args = process.argv.slice(2);

  if (args.length === 0) {
    console.error('Usage: node generate-preview.js <ply-file-path> [output-name]');
    console.error('Example: node generate-preview.js ./gaussians.ply my-scene');
    process.exit(1);
  }

  const [plyPath, outputName] = args;

  generatePreview(plyPath, outputName)
    .then((output) => {
      console.log(`\n✓ Preview generated: ${output}`);
    })
    .catch((err) => {
      console.error('\n✗ Error:', err.message);
      process.exit(1);
    });
}

module.exports = { generatePreview };
