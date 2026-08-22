#!/usr/bin/env node

/**
 * Check production TSX for user-facing literals that bypass react-i18next.
 *
 * This intentionally focuses on the two places where client copy commonly
 * leaks back into the UI: bare JSX text and literal accessibility/content
 * attributes. Dynamic values and strings inside t()/Trans are left alone.
 * Legitimate protocol/product/code literals can be marked with
 * `i18n-exempt` on the same or preceding source line.
 */

import { readdir, readFile, writeFile } from "node:fs/promises";
import { relative, resolve } from "node:path";
import * as ts from "typescript";

const SRC_ROOT = resolve(new URL("../src", import.meta.url).pathname);
const BASELINE_PATH = resolve(
  new URL("./check-i18n-literals-baseline.json", import.meta.url).pathname,
);
const UPDATE_BASELINE = process.argv.includes("--update-baseline");
const EXEMPT_MARKER = "i18n-exempt";
const TARGET_ATTRIBUTES = new Set(["aria-label", "alt", "label", "placeholder", "title"]);
const EXCLUDED_PARTS = ["components/ui", "components/ai-elements"];

function isExcluded(relativePath) {
  return (
    relativePath.endsWith(".test.tsx") || EXCLUDED_PARTS.some((part) => relativePath.includes(part))
  );
}

function hasLetters(value) {
  return /[A-Za-z]{2,}/.test(value);
}

function isTransElement(node) {
  const tagName = node.tagName;
  return ts.isIdentifier(tagName) && tagName.text === "Trans";
}

function isInsideTrans(node) {
  for (let current = node.parent; current; current = current.parent) {
    if (ts.isJsxElement(current) && isTransElement(current.openingElement)) return true;
    if (ts.isJsxSelfClosingElement(current) && isTransElement(current)) return true;
  }
  return false;
}

function lineHasExemption(sourceFile, node) {
  const source = sourceFile.getFullText();
  const line = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line;
  const lines = source.split(/\r?\n/);
  return [line - 1, line, line + 1].some((index) => lines[index]?.includes(EXEMPT_MARKER));
}

function literalText(node) {
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  return null;
}

function collectFiles(directory, output = []) {
  return readdir(directory, { withFileTypes: true }).then(async (entries) => {
    for (const entry of entries) {
      const path = resolve(directory, entry.name);
      if (entry.isDirectory()) {
        await collectFiles(path, output);
      } else if (entry.isFile() && path.endsWith(".tsx")) {
        output.push(path);
      }
    }
    return output;
  });
}

const files = (await collectFiles(SRC_ROOT)).sort();
const violations = [];

for (const filePath of files) {
  const relativePath = relative(SRC_ROOT, filePath).replaceAll("\\", "/");
  if (isExcluded(relativePath)) continue;

  const source = await readFile(filePath, "utf8");
  const sourceFile = ts.createSourceFile(
    filePath,
    source,
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );

  function report(node, value, kind) {
    const text = value.trim();
    if (!text || !hasLetters(text) || lineHasExemption(sourceFile, node)) return;
    const line = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1;
    violations.push({ relativePath, line, kind, text });
  }

  function visit(node) {
    if (ts.isJsxText(node)) {
      if (!isInsideTrans(node)) report(node, node.getText(sourceFile), "JSX text");
    } else if (ts.isJsxAttribute(node)) {
      const attributeName = node.name.text;
      if (TARGET_ATTRIBUTES.has(attributeName) && node.initializer) {
        const text = literalText(node.initializer);
        if (text !== null) report(node, text, `${attributeName} attribute`);
        else if (ts.isJsxExpression(node.initializer) && node.initializer.expression) {
          const expression = node.initializer.expression;
          const expressionText = literalText(expression);
          if (expressionText !== null) report(node, expressionText, `${attributeName} attribute`);
        }
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(sourceFile);
}

function fingerprint(violation) {
  return `${violation.relativePath}\t${violation.kind}\t${violation.text}`;
}

function formatViolation(violation) {
  return `${violation.relativePath}:${violation.line} ${violation.kind}: ${JSON.stringify(violation.text)}`;
}

const fingerprints = [...new Set(violations.map(fingerprint))].sort();
if (UPDATE_BASELINE) {
  await writeFile(BASELINE_PATH, `${JSON.stringify(fingerprints, null, 2)}\n`);
  console.log(`Wrote ${fingerprints.length} baseline i18n literal(s) to ${BASELINE_PATH}`);
  process.exit(0);
}

const baseline = new Set(JSON.parse(await readFile(BASELINE_PATH, "utf8")));
const newViolations = violations.filter((violation) => !baseline.has(fingerprint(violation)));
if (newViolations.length > 0) {
  console.error(`Found ${newViolations.length} new unlocalized TSX literal(s):`);
  for (const violation of newViolations) console.error(`  ${formatViolation(violation)}`);
  console.error(
    "Translate the literal, wrap it in t()/Trans, or mark an intentional value with // " +
      EXEMPT_MARKER +
      ". Existing findings are tracked in the baseline file.",
  );
  process.exitCode = 1;
} else {
  console.log(
    `i18n literal coverage valid: ${violations.length} current finding(s), all present in the baseline`,
  );
}
