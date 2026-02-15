#!/usr/bin/env node

/**
 * Batch generate preview videos for multiple PLY files
 *
 * Usage: node batch-generate-previews.js <ply-file-1> <ply-file-2> ...
 * Or: node batch-generate-previews.js ./plys/*.ply
 */

const { generatePreview } = require('./generate-preview');
const path = require('path');

async function batchGenerate(plyPaths) {
  console.log(`\n🎬 Generating previews for ${plyPaths.length} PLY files...\n`);

  const results = [];

  for (let i = 0; i < plyPaths.length; i++) {
    const plyPath = plyPaths[i];
    const outputName = path.basename(plyPath, '.ply');

    console.log(`[${i + 1}/${plyPaths.length}] Processing ${outputName}...`);

    try {
      const output = await generatePreview(plyPath, outputName);
      results.push({ success: true, input: plyPath, output });
    } catch (err) {
      console.error(`✗ Failed: ${err.message}`);
      results.push({ success: false, input: plyPath, error: err.message });
    }

    console.log(''); // spacing
  }

  // Summary
  console.log('\n' + '='.repeat(60));
  console.log('SUMMARY');
  console.log('='.repeat(60));

  const successful = results.filter(r => r.success);
  const failed = results.filter(r => !r.success);

  console.log(`✓ Successful: ${successful.length}`);
  console.log(`✗ Failed: ${failed.length}`);

  if (successful.length > 0) {
    console.log('\n✓ Generated previews:');
    successful.forEach(r => {
      console.log(`  - ${path.basename(r.output)}`);
    });
  }

  if (failed.length > 0) {
    console.log('\n✗ Failed files:');
    failed.forEach(r => {
      console.log(`  - ${path.basename(r.input)}: ${r.error}`);
    });
  }

  console.log('');
}

// CLI
if (require.main === module) {
  const args = process.argv.slice(2);

  if (args.length === 0) {
    console.error('Usage: node batch-generate-previews.js <ply-file-1> <ply-file-2> ...');
    console.error('Example: node batch-generate-previews.js ./plys/*.ply');
    process.exit(1);
  }

  batchGenerate(args)
    .then(() => {
      console.log('✓ Batch processing complete!');
    })
    .catch((err) => {
      console.error('✗ Batch error:', err.message);
      process.exit(1);
    });
}
