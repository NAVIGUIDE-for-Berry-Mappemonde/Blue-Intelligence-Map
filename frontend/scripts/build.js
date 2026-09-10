#!/usr/bin/env node
/**
 * Build CRA qui ignore UNIQUEMENT le warning webpack de maplibre-gl
 * (« Critical dependency: the request of a dependency is an expression »).
 * Les autres warnings restent des erreurs quand CI=true.
 */
"use strict";

const Module = require("module");

const MAPLIBRE_WARNING =
  /Critical dependency: the request of a dependency is an expression/;

const originalLoad = Module._load;
Module._load = function patchedLoad(request, parent, isMain) {
  const loaded = originalLoad.apply(this, arguments);
  if (request !== "react-dev-utils/formatWebpackMessages") {
    return loaded;
  }
  return function formatWebpackMessages(messages) {
    const formatted = loaded(messages);
    return {
      ...formatted,
      warnings: (formatted.warnings || []).filter(
        (warning) => !MAPLIBRE_WARNING.test(String(warning))
      ),
    };
  };
};

require("react-scripts/scripts/build");
