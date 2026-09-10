#!/usr/bin/env node
/**
 * Copie le worker MapLibre (et le module partagé qu'il importe) vers
 * public/maplibre/. Webpack 5 ne sait pas bundler
 * `new URL(\`./${worker}\`, import.meta.url)` : il émet le warning
 * « Critical dependency » et n'émet pas le fichier. Sans cette copie,
 * le worker 404 en production (URL relative au chunk JS).
 */
"use strict";

const fs = require("fs");
const path = require("path");

const FILES = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];

function copyMaplibreWorker() {
  const distDir = path.join(__dirname, "..", "node_modules", "maplibre-gl", "dist");
  const destDir = path.join(__dirname, "..", "public", "maplibre");
  fs.mkdirSync(destDir, { recursive: true });
  for (const name of FILES) {
    const src = path.join(distDir, name);
    if (!fs.existsSync(src)) {
      throw new Error(
        `Fichier MapLibre manquant : ${src}\n` +
          "Lancer `npm ci` dans frontend/ avant le build."
      );
    }
    fs.copyFileSync(src, path.join(destDir, name));
  }
}

module.exports = { FILES, copyMaplibreWorker };

if (require.main === module) {
  copyMaplibreWorker();
}
