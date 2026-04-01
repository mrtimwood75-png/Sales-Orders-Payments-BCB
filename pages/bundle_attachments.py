import React, { useMemo, useRef, useState } from "react";
import { PDFDocument, StandardFonts, rgb } from "pdf-lib";
import { Download, FileText, Receipt, Upload, Trash2, GripVertical, Image as ImageIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type DocumentType = "confirmation" | "invoice";

type UploadedFile = {
  id: string;
  file: File;
  name: string;
  size: number;
};

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function sanitizeFilename(value: string) {
  return value
    .trim()
    .replace(/\s+/g, "-")
    .replace(/[^a-zA-Z0-9-_]/g, "")
    .replace(/-+/g, "-")
    .toLowerCase();
}

async function fileToArrayBuffer(file: File) {
  return await file.arrayBuffer();
}

async function readImageDimensions(file: File): Promise<{ width: number; height: number; dataUrl: string }> {
  const dataUrl = await new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });

  const dims = await new Promise<{ width: number; height: number }>((resolve, reject) => {
    const img = new window.Image();
    img.onload = () => resolve({ width: img.width, height: img.height });
    img.onerror = reject;
    img.src = dataUrl;
  });

  return { ...dims, dataUrl };
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

function moveItem<T>(items: T[], fromIndex: number, toIndex: number) {
  const copy = [...items];
  const [moved] = copy.splice(fromIndex, 1);
  copy.splice(toIndex, 0, moved);
  return copy;
}

function DocumentTypeSegmentedControl({
  value,
  onChange,
}: {
  value: DocumentType;
  onChange: (value: DocumentType) => void;
}) {
  const options = [
    {
      value: "confirmation" as const,
      label: "Confirmation",
      icon: <FileText className="h-4 w-4" />,
    },
    {
      value: "invoice" as const,
      label: "Invoice",
      icon: <Receipt className="h-4 w-4" />,
    },
  ];

  return (
    <div className="space-y-2">
      <div className="text-sm font-medium text-slate-700">Document type</div>
      <div className="inline-flex rounded-2xl border border-slate-200 bg-slate-100 p-1 shadow-sm" role="tablist" aria-label="Document type">
        {options.map((option) => {
          const active = value === option.value;
          return (
            <button
              key={option.value}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onChange(option.value)}
              className={cn(
                "flex min-w-[170px] items-center justify-center gap-2 rounded-xl px-4 py-2.5 text-sm font-semibold transition-all duration-150 focus:outline-none focus:ring-2 focus:ring-slate-400 focus:ring-offset-2",
                active ? "bg-white text-slate-900 shadow" : "text-slate-500 hover:text-slate-700"
              )}
            >
              {option.icon}
              <span>{option.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

async function buildCoverPdf({
  documentType,
  customerName,
  logoFile,
}: {
  documentType: DocumentType;
  customerName: string;
  logoFile?: File | null;
}) {
  const pdf = await PDFDocument.create();
  const page = pdf.addPage([595.28, 841.89]);
  const { width, height } = page.getSize();

  const fontRegular = await pdf.embedFont(StandardFonts.Helvetica);
  const fontBold = await pdf.embedFont(StandardFonts.HelveticaBold);

  page.drawRectangle({ x: 0, y: 0, width, height, color: rgb(1, 1, 1) });

  if (logoFile) {
    const ext = logoFile.type.toLowerCase();
    const imageBytes = await fileToArrayBuffer(logoFile);
    let embeddedImage;

    if (ext.includes("png")) embeddedImage = await pdf.embedPng(imageBytes);
    else if (ext.includes("jpg") || ext.includes("jpeg")) embeddedImage = await pdf.embedJpg(imageBytes);

    if (embeddedImage) {
      const scaled = embeddedImage.scale(1);
      const maxWidth = 180;
      const scale = Math.min(maxWidth / scaled.width, 80 / scaled.height, 1);
      const drawWidth = scaled.width * scale;
      const drawHeight = scaled.height * scale;
      page.drawImage(embeddedImage, {
        x: 56,
        y: height - 72 - drawHeight,
        width: drawWidth,
        height: drawHeight,
      });
    }
  }

  page.drawText(documentType === "invoice" ? "Invoice" : "Confirmation", {
    x: 56,
    y: height - 190,
    size: 28,
    font: fontBold,
    color: rgb(0.07, 0.09, 0.15),
  });

  page.drawText(customerName || "Customer", {
    x: 56,
    y: height - 230,
    size: 16,
    font: fontRegular,
    color: rgb(0.27, 0.31, 0.36),
  });

  page.drawLine({
    start: { x: 56, y: height - 252 },
    end: { x: width - 56, y: height - 252 },
    thickness: 1,
    color: rgb(0.86, 0.88, 0.9),
  });

  page.drawText("Combined file bundle", {
    x: 56,
    y: height - 290,
    size: 13,
    font: fontBold,
    color: rgb(0.07, 0.09, 0.15),
  });

  page.drawText(`Generated: ${new Date().toLocaleDateString("en-AU")}`, {
    x: 56,
    y: height - 315,
    size: 11,
    font: fontRegular,
    color: rgb(0.42, 0.46, 0.5),
  });

  const bytes = await pdf.save();
  return bytes;
}

async function imageFileToSinglePagePdfBytes(file: File) {
  const pdf = await PDFDocument.create();
  const page = pdf.addPage([595.28, 841.89]);
  const { width, height } = page.getSize();

  const imageBytes = await fileToArrayBuffer(file);
  let image;
  if (file.type.includes("png")) image = await pdf.embedPng(imageBytes);
  else image = await pdf.embedJpg(imageBytes);

  const scaled = image.scale(1);
  const ratio = Math.min((width - 64) / scaled.width, (height - 64) / scaled.height);
  const drawWidth = scaled.width * ratio;
  const drawHeight = scaled.height * ratio;

  page.drawImage(image, {
    x: (width - drawWidth) / 2,
    y: (height - drawHeight) / 2,
    width: drawWidth,
    height: drawHeight,
  });

  return await pdf.save();
}

async function combineFilesIntoPdf({
  files,
  documentType,
  customerName,
  logoFile,
}: {
  files: UploadedFile[];
  documentType: DocumentType;
  customerName: string;
  logoFile?: File | null;
}) {
  const mergedPdf = await PDFDocument.create();

  const coverBytes = await buildCoverPdf({ documentType, customerName, logoFile });
  const coverPdf = await PDFDocument.load(coverBytes);
  const coverPages = await mergedPdf.copyPages(coverPdf, coverPdf.getPageIndices());
  coverPages.forEach((page) => mergedPdf.addPage(page));

  for (const item of files) {
    const lower = item.file.name.toLowerCase();
    if (item.file.type === "application/pdf" || lower.endsWith(".pdf")) {
      const bytes = await fileToArrayBuffer(item.file);
      const srcPdf = await PDFDocument.load(bytes);
      const pages = await mergedPdf.copyPages(srcPdf, srcPdf.getPageIndices());
      pages.forEach((page) => mergedPdf.addPage(page));
    } else if (
      item.file.type.startsWith("image/") ||
      lower.endsWith(".png") ||
      lower.endsWith(".jpg") ||
      lower.endsWith(".jpeg")
    ) {
      const imagePdfBytes = await imageFileToSinglePagePdfBytes(item.file);
      const srcPdf = await PDFDocument.load(imagePdfBytes);
      const pages = await mergedPdf.copyPages(srcPdf, srcPdf.getPageIndices());
      pages.forEach((page) => mergedPdf.addPage(page));
    }
  }

  const mergedBytes = await mergedPdf.save();
  return new Blob([mergedBytes], { type: "application/pdf" });
}

export default function LogoAndBundleApp() {
  const [documentType, setDocumentType] = useState<DocumentType>("confirmation");
  const [customerName, setCustomerName] = useState("");
  const [uploadedFiles, setUploadedFiles] = useState<UploadedFile[]>([]);
  const [logoFile, setLogoFile] = useState<File | null>(null);
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  const [isProcessing, setIsProcessing] = useState(false);
  const [draggedIndex, setDraggedIndex] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const logoInputRef = useRef<HTMLInputElement | null>(null);

  const outputFilename = useMemo(() => {
    const name = sanitizeFilename(customerName || "customer");
    return `${name}-${documentType}.pdf`;
  }, [customerName, documentType]);

  const previewTitle = documentType === "invoice" ? "Invoice" : "Confirmation";

  const addFiles = (fileList: FileList | null) => {
    if (!fileList) return;

    const validFiles = Array.from(fileList).filter((file) => {
      const lower = file.name.toLowerCase();
      return (
        file.type === "application/pdf" ||
        file.type.startsWith("image/") ||
        lower.endsWith(".pdf") ||
        lower.endsWith(".png") ||
        lower.endsWith(".jpg") ||
        lower.endsWith(".jpeg")
      );
    });

    const mapped = validFiles.map((file, index) => ({
      id: `${file.name}-${file.size}-${Date.now()}-${index}`,
      file,
      name: file.name,
      size: file.size,
    }));

    setUploadedFiles((prev) => [...prev, ...mapped]);
  };

  const removeFile = (id: string) => {
    setUploadedFiles((prev) => prev.filter((item) => item.id !== id));
  };

  const onDragStartRow = (index: number) => setDraggedIndex(index);
  const onDropRow = (index: number) => {
    if (draggedIndex === null || draggedIndex === index) return;
    setUploadedFiles((prev) => moveItem(prev, draggedIndex, index));
    setDraggedIndex(null);
  };

  const handleCombineAndDownload = async () => {
    if (uploadedFiles.length === 0) return;

    try {
      setIsProcessing(true);
      setError(null);

      const blob = await combineFilesIntoPdf({
        files: uploadedFiles,
        documentType,
        customerName,
        logoFile,
      });

      downloadBlob(blob, outputFilename);
    } catch (err) {
      console.error(err);
      setError("Failed to combine and download the PDF.");
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 p-6">
      <div className="mx-auto grid max-w-7xl gap-6 lg:grid-cols-[1.05fr_0.95fr]">
        <Card className="rounded-3xl border-slate-200 shadow-sm">
          <CardContent className="grid gap-6 p-6">
            <div className="flex items-start justify-between gap-4">
              <div>
                <h1 className="text-2xl font-bold tracking-tight text-slate-900">Logo and bundle PDF app</h1>
                <p className="mt-1 text-sm text-slate-500">Upload a logo, choose document type, combine files, and download one PDF.</p>
              </div>
              <Button
                type="button"
                variant="outline"
                className="rounded-2xl"
                onClick={() => {
                  setUploadedFiles([]);
                  setLogoFile(null);
                  setCustomerName("");
                  setDocumentType("confirmation");
                  setError(null);
                }}
              >
                Reset
              </Button>
            </div>

            <div className="grid gap-5 xl:grid-cols-2">
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700">Customer name</label>
                <input
                  value={customerName}
                  onChange={(e) => setCustomerName(e.target.value)}
                  placeholder="Enter customer name"
                  className="h-12 w-full rounded-2xl border border-slate-200 bg-white px-4 text-sm text-slate-900 outline-none transition focus:border-slate-300 focus:ring-2 focus:ring-slate-200"
                />
              </div>

              <DocumentTypeSegmentedControl value={documentType} onChange={setDocumentType} />
            </div>

            <div className="grid gap-5 xl:grid-cols-2">
              <div className="space-y-2">
                <div className="text-sm font-medium text-slate-700">Logo</div>
                <input
                  ref={logoInputRef}
                  type="file"
                  accept="image/png,image/jpeg,image/jpg"
                  className="hidden"
                  onChange={(e) => setLogoFile(e.target.files?.[0] || null)}
                />
                <button
                  type="button"
                  onClick={() => logoInputRef.current?.click()}
                  className="flex h-28 w-full items-center justify-center gap-3 rounded-2xl border border-dashed border-slate-300 bg-white px-4 text-sm text-slate-600 transition hover:border-slate-400 hover:text-slate-800"
                >
                  <ImageIcon className="h-5 w-5" />
                  {logoFile ? `${logoFile.name} (${formatBytes(logoFile.size)})` : "Upload logo"}
                </button>
              </div>

              <div className="space-y-2">
                <div className="text-sm font-medium text-slate-700">Files to bundle</div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept="application/pdf,image/png,image/jpeg"
                  multiple
                  className="hidden"
                  onChange={(e) => addFiles(e.target.files)}
                />
                <button
                  type="button"
                  onClick={() => fileInputRef.current?.click()}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setIsDraggingOver(true);
                  }}
                  onDragLeave={() => setIsDraggingOver(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setIsDraggingOver(false);
                    addFiles(e.dataTransfer.files);
                  }}
                  className={cn(
                    "flex h-28 w-full items-center justify-center gap-3 rounded-2xl border border-dashed bg-white px-4 text-sm transition",
                    isDraggingOver
                      ? "border-slate-500 text-slate-900"
                      : "border-slate-300 text-slate-600 hover:border-slate-400 hover:text-slate-800"
                  )}
                >
                  <Upload className="h-5 w-5" />
                  Upload or drop PDF / image files
                </button>
              </div>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-sm font-medium text-slate-700">Bundle order</div>
                <div className="text-xs text-slate-500">Drag rows to reorder</div>
              </div>

              <div className="grid gap-2">
                {uploadedFiles.length === 0 ? (
                  <div className="rounded-2xl border border-slate-200 bg-white px-4 py-5 text-sm text-slate-500">
                    No files added yet.
                  </div>
                ) : (
                  uploadedFiles.map((item, index) => (
                    <div
                      key={item.id}
                      draggable
                      onDragStart={() => onDragStartRow(index)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={() => onDropRow(index)}
                      className="flex items-center justify-between gap-3 rounded-2xl border border-slate-200 bg-white px-4 py-3 shadow-sm"
                    >
                      <div className="flex min-w-0 items-center gap-3">
                        <GripVertical className="h-4 w-4 shrink-0 text-slate-400" />
                        <div className="min-w-0">
                          <div className="truncate text-sm font-medium text-slate-900">{item.name}</div>
                          <div className="text-xs text-slate-500">{formatBytes(item.size)}</div>
                        </div>
                      </div>

                      <Button type="button" variant="ghost" size="icon" className="rounded-xl" onClick={() => removeFile(item.id)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  ))
                )}
              </div>
            </div>

            {error ? (
              <div className="rounded-2xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
            ) : null}

            <div className="flex flex-wrap items-center gap-3">
              <Button
                type="button"
                size="lg"
                disabled={uploadedFiles.length === 0 || isProcessing}
                onClick={handleCombineAndDownload}
                className="h-12 rounded-2xl px-6 text-base font-semibold"
              >
                <Download className="mr-2 h-4 w-4" />
                {isProcessing ? "Combining PDF..." : `Combine & download PDF${uploadedFiles.length ? ` (${uploadedFiles.length} files)` : ""}`}
              </Button>

              <div className="text-sm text-slate-500">Output: {outputFilename}</div>
            </div>
          </CardContent>
        </Card>

        <Card className="rounded-3xl border-slate-200 shadow-sm">
          <CardContent className="p-6">
            <div className="rounded-[28px] border border-slate-200 bg-white p-8 shadow-sm">
              <div className="flex min-h-[760px] flex-col">
                <div className="flex items-start justify-between gap-4 border-b border-slate-200 pb-6">
                  <div>
                    <div className="text-xs font-medium uppercase tracking-[0.18em] text-slate-400">Preview</div>
                    <div className="mt-3 text-4xl font-bold tracking-tight text-slate-900">{previewTitle}</div>
                    <div className="mt-2 text-base text-slate-500">{customerName || "Customer name"}</div>
                  </div>

                  <div className="rounded-2xl border border-slate-200 px-4 py-2 text-sm text-slate-500">
                    {uploadedFiles.length} bundled {uploadedFiles.length === 1 ? "file" : "files"}
                  </div>
                </div>

                <div className="mt-8 grid gap-4">
                  <div className="rounded-2xl bg-slate-50 p-5">
                    <div className="text-sm font-medium text-slate-700">Document type</div>
                    <div className="mt-2 text-lg font-semibold text-slate-900">{previewTitle}</div>
                  </div>

                  <div className="rounded-2xl bg-slate-50 p-5">
                    <div className="text-sm font-medium text-slate-700">Included files</div>
                    <div className="mt-3 grid gap-2">
                      {uploadedFiles.length === 0 ? (
                        <div className="text-sm text-slate-500">Your bundled files will appear here.</div>
                      ) : (
                        uploadedFiles.map((item, index) => (
                          <div key={item.id} className="flex items-center justify-between rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm">
                            <span className="truncate pr-3 text-slate-800">{index + 1}. {item.name}</span>
                            <span className="shrink-0 text-slate-500">{formatBytes(item.size)}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>

                  <div className="rounded-2xl bg-slate-50 p-5">
                    <div className="text-sm font-medium text-slate-700">Logo</div>
                    <div className="mt-2 text-sm text-slate-500">{logoFile ? logoFile.name : "No logo uploaded"}</div>
                  </div>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/*
INSTALL
npm install pdf-lib lucide-react

NOTES
- This is a complete front-end React file.
- It combines uploaded PDF files and image files into one PDF.
- It inserts a generated first page using the selected document type.
- The segmented control toggles Confirmation / Invoice.
- The main button combines and immediately downloads the PDF.
- Replace the preview styling or generated cover page layout if you want it to match your existing app exactly.
*/
