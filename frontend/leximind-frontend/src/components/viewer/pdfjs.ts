// Central pdf.js (pdfjs-dist v6) setup. Importing this module once wires up the worker via a
// Vite `?url` import so the worker file is bundled and served correctly. Everything else in the
// viewer imports pdf.js through here so the worker is guaranteed to be configured first.

import * as pdfjsLib from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjsLib.GlobalWorkerOptions.workerSrc = workerUrl;

export { pdfjsLib };
export type PdfDocumentProxy = Awaited<ReturnType<typeof pdfjsLib.getDocument>["promise"]>;
export type PdfPageProxy = Awaited<ReturnType<PdfDocumentProxy["getPage"]>>;
export type PdfOutline = Awaited<ReturnType<PdfDocumentProxy["getOutline"]>>;
export type PdfOutlineNode = PdfOutline extends (infer T)[] ? T : never;
