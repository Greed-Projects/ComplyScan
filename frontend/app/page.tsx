"use client";

import { ChangeEvent, DragEvent, useMemo, useState } from "react";

type CheckStatus = "pass" | "warning" | "fail" | "not_applicable";
type PackageForm = "single" | "combination" | "group" | "multi_piece";
type CommodityClass = "general" | "tobacco" | "pan_masala";

type Point = { x: number; y: number };

type OcrRegion = {
  id: string;
  text: string;
  confidence: number;
  polygon: Point[];
  bbox: [number, number, number, number];
  source: string;
  source_image_id?: string | null;
};

type PackageContext = {
  imported_product: boolean;
  may_become_unfit_for_human_consumption: boolean;
  dimensions_relevant: boolean;
  package_form: PackageForm;
  alcoholic_beverage: boolean;
  commodity_class: CommodityClass;
};

type RuleProfile = {
  id: string;
  title: string;
  jurisdiction: string;
  legal_basis: string;
  checked_through: string;
  scope: string;
  exclusions: string[];
};

type DeclarationCheck = {
  rule_id: string;
  key: string;
  label: string;
  legal_reference: string;
  requirement: string;
  applicability: "required" | "not_applicable";
  status: CheckStatus;
  value?: string | null;
  evidence?: string | null;
  confidence: number;
  message: string;
  region_ids: string[];
  source_image_ids: string[];
  attributes: Record<string, string>;
};

type ExtractedDeclaration = {
  key: string;
  label: string;
  value: string;
  evidence: string;
  confidence: number;
  attributes: Record<string, string>;
  region_ids: string[];
  source_image_ids: string[];
};

type OcrVariantTrace = {
  crop: string;
  variant: string;
  family: string;
  text?: string | null;
  parsed_value?: string | null;
  confidence: number;
};

type OcrRecoveryTrace = {
  declaration_key: string;
  locator: string;
  reference_evidence: string;
  attempted: boolean;
  resolved: boolean;
  attempts: number;
  strategy?: string | null;
  recovered_text?: string | null;
  region_ids: string[];
  variants: OcrVariantTrace[];
  message: string;
  source_image_id?: string | null;
};

type PackageImageAnalysis = {
  image_id: string;
  file_name: string;
  ocr_engine: string;
  ocr_text: string;
  image: { width: number; height: number };
  regions: OcrRegion[];
  ocr_recovery: OcrRecoveryTrace[];
  declarations: ExtractedDeclaration[];
};

type AnalysisResponse = {
  input_mode: "images" | "manual_text";
  file_names: string[];
  image_count: number;
  images: PackageImageAnalysis[];
  ocr_text: string;
  declarations: ExtractedDeclaration[];
  context: PackageContext;
  ruleset: string;
  rule_profile: RuleProfile;
  summary: {
    score: number | null;
    status: CheckStatus;
    passed: number;
    warnings: number;
    failed: number;
    not_applicable: number;
  };
  checks: DeclarationCheck[];
  disclaimer: string;
};

const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");
const MAX_IMAGES = 6;

const DEMO_TEXT = `Product Name: Cleaning Powder
Manufactured by: Innovate X Consumer Products Pvt. Ltd., Sector 62, Noida, Uttar Pradesh 201309
Net Quantity: 200 g
MRP: Rs. 99.00 Inclusive of all taxes
Mfg Date: 08/2026
Consumer Care: Innovate X Consumer Products Pvt. Ltd., Sector 62, Noida 201309 | care@innovatex.example | 9876543210
Unit Sale Price: Rs. 0.50 / g`;

function statusLabel(status: CheckStatus) {
  if (status === "pass") return "Compliant evidence";
  if (status === "warning") return "Review";
  if (status === "fail") return "Missing / invalid";
  return "Not applicable";
}

export default function Home() {
  const [files, setFiles] = useState<File[]>([]);
  const [previews, setPreviews] = useState<string[]>([]);
  const [activeImageIndex, setActiveImageIndex] = useState(0);
  const [manualText, setManualText] = useState("");
  const [result, setResult] = useState<AnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [legalContext, setLegalContext] = useState<PackageContext>({
    imported_product: false,
    may_become_unfit_for_human_consumption: false,
    dimensions_relevant: false,
    package_form: "single",
    alcoholic_beverage: false,
    commodity_class: "general",
  });

  const canAnalyze = Boolean(files.length || manualText.trim());
  const activeImage = result?.images[activeImageIndex] ?? null;
  const activePreview = previews[activeImageIndex] ?? null;
  const recoveryTraces = useMemo(() => result?.images.flatMap((image) => image.ocr_recovery) ?? [], [result]);

  const scoreTone = useMemo(() => {
    if (!result || result.summary.score === null) return "neutral";
    if (result.summary.score >= 85 && result.summary.failed === 0) return "good";
    if (result.summary.score >= 55) return "warn";
    return "bad";
  }, [result]);

  const regionFindings = useMemo(() => {
    const map = new Map<string, DeclarationCheck>();
    if (!result) return map;
    for (const check of result.checks) {
      if (check.status === "not_applicable") continue;
      for (const regionId of check.region_ids) map.set(regionId, check);
    }
    return map;
  }, [result]);

  const evidenceRegions = useMemo(() => {
    if (!activeImage) return [];
    return activeImage.regions.filter((region) => regionFindings.has(region.id));
  }, [activeImage, regionFindings]);

  function replaceFiles(nextFiles: File[]) {
    for (const url of previews) URL.revokeObjectURL(url);
    const accepted = nextFiles.slice(0, MAX_IMAGES);
    setFiles(accepted);
    setPreviews(accepted.map((file) => URL.createObjectURL(file)));
    setActiveImageIndex(0);
    setResult(null);
    setError(nextFiles.length > MAX_IMAGES ? `Only the first ${MAX_IMAGES} images were selected.` : "");
    if (accepted.length) setManualText("");
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    replaceFiles(Array.from(event.target.files ?? []));
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    setDragging(false);
    replaceFiles(Array.from(event.dataTransfer.files ?? []).filter((file) => file.type.startsWith("image/")));
  }

  function loadDemo() {
    replaceFiles([]);
    setManualText(DEMO_TEXT);
    setLegalContext({
      imported_product: false,
      may_become_unfit_for_human_consumption: false,
      dimensions_relevant: false,
      package_form: "single",
      alcoholic_beverage: false,
      commodity_class: "general",
    });
    setResult(null);
  }

  function setContext<K extends keyof PackageContext>(key: K, value: PackageContext[K]) {
    setLegalContext((current) => ({ ...current, [key]: value }));
    setResult(null);
  }

  async function analyze() {
    if (!canAnalyze) return;
    setLoading(true);
    setError("");
    setResult(null);

    const data = new FormData();
    for (const file of files) data.append("files", file);
    if (manualText.trim()) data.append("override_text", manualText.trim());
    data.append("imported_product", String(legalContext.imported_product));
    data.append("may_become_unfit_for_human_consumption", String(legalContext.may_become_unfit_for_human_consumption));
    data.append("dimensions_relevant", String(legalContext.dimensions_relevant));
    data.append("package_form", legalContext.package_form);
    data.append("alcoholic_beverage", String(legalContext.alcoholic_beverage));
    data.append("commodity_class", legalContext.commodity_class);

    try {
      const response = await fetch(`${API_URL}/api/analyze`, { method: "POST", body: data });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail ?? "Analysis failed");
      setResult(payload as AnalysisResponse);
      setActiveImageIndex(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach the analysis service.");
    } finally {
      setLoading(false);
    }
  }

  function downloadReport() {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    const baseName = result.file_names[0]?.replace(/\.[^.]+$/, "") || "report";
    anchor.href = url;
    anchor.download = `packcheck-${baseName}${result.image_count > 1 ? `-${result.image_count}-views` : ""}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <main>
      <header className="topbar">
        <div className="brand">
          <div className="brandMark">PX</div>
          <div><strong>PackCheck AI</strong><span>Legal Metrology screening prototype</span></div>
        </div>
        <div className="badge">SIH 2026 · PS 26034 · v0.8</div>
      </header>

      <section className="hero shell">
        <div>
          <span className="eyebrow">Multi-view package inspection</span>
          <h1>Combine evidence from every visible side of the same package.</h1>
          <p>
            Upload front, back, side, seal or bottom views together. PackCheck runs computer vision and OCR per image, then fuses declarations into one auditable Legal Metrology inspection without silently resolving conflicting values.
          </p>
          <div className="techRow">
            <span>PP-OCRv6 · ONNX Runtime</span><span>CV + image variants</span><span>Direct recognition fallback</span><span>Cross-image evidence fusion</span><span>Versioned LMPC profile</span>
          </div>
        </div>
        <div className="heroMetric"><span>Package views</span><strong>{files.length || "1–6"}</strong><small>one combined inspection</small></div>
      </section>

      <section className="workspace shell">
        <div className="panel inputPanel">
          <div className="panelHead">
            <div><span className="step">01</span><h2>Capture package views</h2></div>
            <button className="textButton" onClick={loadDemo}>Load demo</button>
          </div>

          <label className={`dropzone ${dragging ? "dragging" : ""}`} onDragOver={(event) => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)} onDrop={onDrop}>
            <input type="file" accept="image/*" multiple onChange={onFileChange} />
            {previews.length ? (
              <div className="multiPreview">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img className="preview" src={previews[0]} alt="First selected package view" />
                <div className="viewCountBadge">{files.length} view{files.length === 1 ? "" : "s"}</div>
              </div>
            ) : (
              <div className="dropCopy"><div className="uploadIcon">↑</div><strong>Drop one or more package images here</strong><span>front · back · side · seal · bottom · up to 6 images</span></div>
            )}
          </label>

          {files.length > 0 && (
            <div className="selectedViews">
              {files.map((file, index) => (
                <button key={`${file.name}-${file.lastModified}-${index}`} className={`selectedView ${activeImageIndex === index ? "active" : ""}`} onClick={() => setActiveImageIndex(index)} type="button">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={previews[index]} alt="" />
                  <span>{index + 1}</span><small>{file.name}</small>
                </button>
              ))}
            </div>
          )}

          <div className="or"><span>OR</span></div>
          <label className="fieldLabel" htmlFor="labelText">Paste label text for a deterministic demo</label>
          <textarea id="labelText" value={manualText} onChange={(event) => { setManualText(event.target.value); if (event.target.value.trim()) replaceFiles([]); }} placeholder="Use this to demonstrate the compliance engine without OCR..." />

          <details className="contextBox">
            <summary>Package context · controls legal applicability</summary>
            <p className="contextHint">Context applies to the physical package as a whole, not to an individual photograph.</p>
            <div className="contextGrid">
              <label className="toggleField"><input type="checkbox" checked={legalContext.imported_product} onChange={(event) => setContext("imported_product", event.target.checked)} /><span>Imported product</span></label>
              <label className="toggleField"><input type="checkbox" checked={legalContext.may_become_unfit_for_human_consumption} onChange={(event) => setContext("may_become_unfit_for_human_consumption", event.target.checked)} /><span>May become unfit for human consumption</span></label>
              <label className="toggleField"><input type="checkbox" checked={legalContext.dimensions_relevant} onChange={(event) => setContext("dimensions_relevant", event.target.checked)} /><span>Dimensions relevant to sale/use</span></label>
              <label className="toggleField"><input type="checkbox" checked={legalContext.alcoholic_beverage} onChange={(event) => setContext("alcoholic_beverage", event.target.checked)} /><span>Alcoholic / spirituous beverage</span></label>
              <label className="selectField"><span>Package form</span><select value={legalContext.package_form} onChange={(event) => setContext("package_form", event.target.value as PackageForm)}><option value="single">Single package</option><option value="combination">Combination package</option><option value="group">Group package</option><option value="multi_piece">Multi-piece package</option></select></label>
              <label className="selectField"><span>Commodity class</span><select value={legalContext.commodity_class} onChange={(event) => setContext("commodity_class", event.target.value as CommodityClass)}><option value="general">General</option><option value="tobacco">Tobacco / tobacco product</option><option value="pan_masala">Pan masala</option></select></label>
            </div>
          </details>

          {error && <div className="errorBox">{error}</div>}
          <button className="primaryButton" disabled={!canAnalyze || loading} onClick={analyze}>{loading ? `Analyzing ${files.length > 1 ? `${files.length} views` : "package"}…` : "Run package inspection"}</button>
          <p className="firstRunNote">Each image is OCR-processed independently. Difficult referenced regions can trigger the verified CV + direct-recognition fallback before evidence is fused.</p>
        </div>

        <div className="panel resultPanel">
          <div className="panelHead"><div><span className="step">02</span><h2>Combined compliance findings</h2></div>{result && <button className="textButton" onClick={downloadReport}>Export JSON</button>}</div>

          {!result ? (
            <div className="emptyState"><div className="radar">◎</div><h3>Ready for inspection</h3><p>Upload several views of the same package to combine distributed declarations into one result.</p></div>
          ) : (
            <div className="results">
              <div className={`scoreCard ${scoreTone}`}>
                <div><span>Applicable-rule score</span>{result.summary.score === null ? <strong className="naScore">N/A</strong> : <strong>{result.summary.score}<small>/100</small></strong>}</div>
                <div className="scoreStats"><span><b>{result.summary.passed}</b> compliant evidence</span><span><b>{result.summary.warnings}</b> review</span><span><b>{result.summary.failed}</b> missing / invalid</span><span><b>{result.summary.not_applicable}</b> not applicable</span></div>
              </div>

              {result.input_mode === "images" && (
                <section className="inspectionSummary"><div><span className="miniLabel">Inspection evidence</span><h3>{result.image_count} package view{result.image_count === 1 ? "" : "s"} fused</h3><p>{result.declarations.length} structured declaration facts were assembled across the uploaded views.</p></div><div className="inspectionFiles">{result.file_names.map((name, index) => <span key={`${name}-${index}`}>{index + 1}. {name}</span>)}</div></section>
              )}

              <section className="profileCard"><div><span className="miniLabel">Active legal profile</span><h3>{result.rule_profile.title}</h3><p>{result.rule_profile.legal_basis}</p></div><span className="profileDate">Checked through {result.rule_profile.checked_through}</span></section>

              {recoveryTraces.length > 0 && (
                <section className="recoveryCard"><div className="recoveryHead"><div><span className="miniLabel">Targeted OCR recovery</span><h3>Referenced declarations</h3></div><span className="regionCount">{recoveryTraces.length} reference{recoveryTraces.length > 1 ? "s" : ""}</span></div><div className="recoveryItems">
                  {recoveryTraces.map((trace, index) => {
                    const source = result.images.find((image) => image.image_id === trace.source_image_id);
                    return <article className={`recoveryItem ${trace.resolved ? "resolved" : "unresolved"}`} key={`${trace.source_image_id}-${trace.declaration_key}-${index}`}><div className="recoveryStatus">{trace.resolved ? "Resolved" : "Review"}</div><div><b>{trace.declaration_key.toUpperCase()} · {trace.locator}{source ? ` · ${source.file_name}` : ""}</b><p>{trace.message}</p><code>{trace.reference_evidence}</code><small>{trace.attempted ? `${trace.attempts} localized OCR attempt${trace.attempts === 1 ? "" : "s"}` : "Direct value already available"}{trace.strategy ? ` · ${trace.strategy}` : ""}</small>{trace.variants.length > 0 && <details className="variantDetails"><summary>Show preprocessing / OCR variants</summary><div className="variantGrid">{trace.variants.map((variant, variantIndex) => <div className={`variantRow ${variant.parsed_value ? "parsed" : ""}`} key={`${variant.crop}-${variant.variant}-${variantIndex}`}><div><b>{variant.variant}</b><span>{variant.family} · {Math.round(variant.confidence * 100)}%</span></div><code>{variant.parsed_value ?? "No price candidate"}</code><p>{variant.text ?? "No text detected"}</p></div>)}</div></details>}</div></article>;
                  })}
                </div></section>
              )}

              {activeImage && activePreview && (
                <section className="visualEvidence">
                  <div className="evidenceHead"><div><span className="miniLabel">Visual evidence</span><h3>{activeImage.file_name}</h3></div><span className="regionCount">{activeImage.regions.length} OCR regions</span></div>
                  {result.images.length > 1 && <div className="evidenceTabs">{result.images.map((image, index) => <button type="button" key={image.image_id} className={activeImageIndex === index ? "active" : ""} onClick={() => setActiveImageIndex(index)}>{index + 1}<span>{image.file_name}</span></button>)}</div>}
                  <div className="evidenceImageWrap">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={activePreview} alt="Package with OCR evidence overlay" className="evidenceImage" />
                    <svg className="evidenceOverlay" viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-label="OCR evidence boxes">{evidenceRegions.map((region) => { const finding = regionFindings.get(region.id); const points = region.polygon.map((point) => `${point.x * 1000},${point.y * 1000}`).join(" "); return <polygon key={region.id} points={points} className={`evidencePolygon ${finding?.status ?? "warning"}`}><title>{`${finding?.label ?? "OCR text"}: ${region.text} (${Math.round(region.confidence * 100)}%) · ${region.source}`}</title></polygon>; })}</svg>
                  </div>
                  <div className="evidenceLegend"><span><i className="legendSwatch pass" />Evidence used by the combined inspection</span><span>Switch views to inspect where each declaration came from.</span></div>
                </section>
              )}

              <div className="checks">{result.checks.map((check) => <article className={`check ${check.status}`} key={check.rule_id}><div className={`statusDot ${check.status}`} /><div className="checkBody"><div className="checkTop"><h3>{check.label}</h3><span className={`statusPill ${check.status}`}>{statusLabel(check.status)}</span></div><div className="ruleRef">{check.rule_id} · {check.legal_reference}</div><p>{check.message}</p>{check.value && <div className="normalizedValue"><span>Normalized</span><b>{check.value}</b></div>}{check.evidence && <code>{check.evidence}</code>}<details className="requirementDetail"><summary>Requirement</summary><p>{check.requirement}</p></details><small>Confidence: {Math.round(check.confidence * 100)}%{check.source_image_ids.length > 0 ? ` · evidence from ${check.source_image_ids.length} view${check.source_image_ids.length > 1 ? "s" : ""}` : ""}{check.region_ids.length > 0 ? ` · ${check.region_ids.length} visual region${check.region_ids.length > 1 ? "s" : ""}` : ""}</small></div></article>)}</div>

              <details className="ocrBox"><summary>View OCR extraction and profile metadata</summary><div className="ocrMeta">Ruleset: {result.ruleset} · Views: {result.image_count} · Targeted recoveries: {recoveryTraces.filter((item) => item.resolved).length}</div><pre>{result.ocr_text || "No text extracted."}</pre></details>
              <div className="disclaimer">{result.disclaimer}</div>
            </div>
          )}
        </div>
      </section>

      <section className="scope shell">
        <div><span className="scopeIcon">✓</span><b>Included now</b><p>Multi-image package inspection, cross-view declaration fusion, explicit conflict review, CV target localization, multi-view preprocessing, detector-free difficult-text recognition and versioned LMPC evaluation.</p></div>
        <div><span className="scopeIcon muted">→</span><b>Next phase</b><p>Principal display panel geometry, physical font/numeral-size calibration, perspective-aware measurement and specialized product-rule profiles.</p></div>
      </section>
    </main>
  );
}
