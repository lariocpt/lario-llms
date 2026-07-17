const fs = require('fs');
const http = require('https');

const url = process.argv[2];
const outFile = process.argv[3];
const concurrency = parseInt(process.argv[4] || '16');

if (!url || !outFile) {
  console.log("Usage: node fast_download.js <url> <outFile> [concurrency]");
  process.exit(1);
}

function getHeaders(url) {
  return new Promise((resolve, reject) => {
    const req = http.request(url, { method: 'HEAD' }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        resolve(getHeaders(res.headers.location));
      } else {
        resolve({
          size: parseInt(res.headers['content-length'] || '0'),
          url: url
        });
      }
    });
    req.on('error', reject);
    req.end();
  });
}

function downloadChunk(url, start, end, chunkPath) {
  return new Promise((resolve, reject) => {
    const file = fs.createWriteStream(chunkPath);
    const req = http.get(url, {
      headers: { 'Range': `bytes=${start}-${end}` }
    }, (res) => {
      if (res.statusCode >= 300 && res.statusCode < 400 && res.headers.location) {
        reject(new Error("Redirect in range request"));
        return;
      }
      res.pipe(file);
      file.on('finish', () => {
        file.close();
        resolve();
      });
    });

    req.setTimeout(25000, () => {
      req.destroy(new Error("Socket timeout after 25s"));
    });

    req.on('error', (err) => {
      file.close();
      try { fs.unlinkSync(chunkPath); } catch (e) {}
      reject(err);
    });
  });
}

async function downloadChunkWithRetry(url, start, end, chunkPath) {
  const maxAttempts = 25;
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      await downloadChunk(url, start, end, chunkPath);
      return; // Success!
    } catch (err) {
      if (attempt === maxAttempts) {
        throw err; // Final failure
      }
      console.warn(`  Part [${start}-${end}] failed (Attempt ${attempt}/${maxAttempts}): ${err.message}. Retrying in 2s...`);
      await new Promise(resolve => setTimeout(resolve, 2000));
    }
  }
}

async function main() {
  console.log(`Resolving headers for ${url}...`);
  const { size, url: directUrl } = await getHeaders(url);
  console.log(`Direct URL: ${directUrl}`);
  console.log(`File size: ${(size / 1024 / 1024).toFixed(2)} MB`);

  if (size === 0) {
    throw new Error("Could not determine file size");
  }

  const chunkSize = Math.ceil(size / concurrency);
  const chunks = [];
  const chunkPaths = [];

  for (let i = 0; i < concurrency; i++) {
    const start = i * chunkSize;
    const end = Math.min(start + chunkSize - 1, size - 1);
    const chunkPath = `${outFile}.part${i}`;
    chunks.push({ start, end, chunkPath });
    chunkPaths.push(chunkPath);
  }

  console.log(`Downloading in ${concurrency} parallel parts...`);
  const startTime = Date.now();

  await Promise.all(chunks.map((c, i) => {
    return downloadChunkWithRetry(directUrl, c.start, c.end, c.chunkPath).then(() => {
      console.log(`  Part ${i} finished [${c.start}-${c.end}]`);
    }).catch(err => {
      console.error(`  Part ${i} failed:`, err);
      throw err;
    });
  }));

  const downloadTime = ((Date.now() - startTime) / 1000).toFixed(2);
  console.log(`Download finished in ${downloadTime}s. Merging parts...`);

  const dest = fs.createWriteStream(outFile);
  for (const chunkPath of chunkPaths) {
    const data = fs.readFileSync(chunkPath);
    dest.write(data);
    fs.unlinkSync(chunkPath);
  }
  dest.end();

  console.log(`Successfully saved to ${outFile}!`);
}

main().catch(err => {
  console.error("Error:", err);
  process.exit(1);
});
