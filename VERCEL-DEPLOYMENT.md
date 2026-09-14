# Vercel Deployment

ComplyScan v0.8 can run entirely on Vercel as two projects created from the same GitHub repository:

```text
Greed-Projects/ComplyScan
├── frontend/ -> Vercel Next.js project
└── backend/  -> Vercel FastAPI / Python project
```

The browser sends each package photo to the OCR backend as a separate request and then sends only structured JSON evidence to the fusion endpoint. This keeps multi-view inspection intact without proxying several large images through one Vercel Function request.

## 1. Deploy the backend first

Import the GitHub repository into Vercel and create a project for the OCR API.

Configure:

- **Project Name:** `complyscan-api`
- **Root Directory:** `backend`
- **Framework:** Vercel should detect the Python/FastAPI application
- **Python:** `3.13` from `backend/.python-version`

The repository already provides:

- `[tool.vercel].entrypoint = "app.main:app"`
- `backend/vercel.json`
- a 300-second function duration
- deployment bundle exclusions for tests, local virtual environments and diagnostics

After deployment, verify:

```text
https://<your-backend-domain>/health
```

Expected service identifier:

```json
{"status":"ok","service":"complyscan-api", ...}
```

### PaddleOCR model cache on Vercel

Vercel Functions have a writable `/tmp` directory. When `VERCEL` is present, ComplyScan automatically configures PaddleX to use:

```text
PADDLE_PDX_CACHE_HOME=/tmp/complyscan-paddlex
PADDLE_PDX_MODEL_SOURCE=bos
PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=1
```

The first OCR invocation on a new function instance can therefore be much slower because PP-OCRv6 models may need to be downloaded into that instance's temporary cache. Warm instances reuse the cache.

## 2. Deploy the frontend

Create a second Vercel project from the same GitHub repository.

Configure:

- **Project Name:** `complyscan`
- **Root Directory:** `frontend`
- **Framework Preset:** Next.js
- **Build Command:** package default (`npm run build`)
- **Environment Variable:**

```text
NEXT_PUBLIC_API_URL=https://<your-backend-domain>
```

The frontend reads `NEXT_PUBLIC_API_URL` at build time, so redeploy after changing it.

## 3. Allow the frontend origin on the backend

After Vercel assigns the production frontend domain, add this environment variable to the backend project:

```text
COMPLYSCAN_ALLOWED_ORIGINS=https://<your-frontend-domain>
```

Then redeploy the backend.

Multiple allowed origins can be comma-separated.

Local development origins remain enabled automatically:

```text
http://localhost:3000
http://127.0.0.1:3000
```

## Hosted image transport

Local FastAPI usage still supports the original limits:

- up to 6 images
- 10 MB per image
- 40 MB combined

For a hosted HTTPS API, the frontend caps each selected image at **4,000,000 bytes** and sends images one at a time:

```text
Browser
  |
  +-- image 1 --> POST /api/analyze/image
  +-- image 2 --> POST /api/analyze/image
  +-- ...
  |
  +-- compact declarations/OCR text --> POST /api/analyze/fuse
                                      |
                                      v
                            combined legal result
```

Images are **not silently recompressed**. If a hosted image exceeds the safe limit, the UI rejects that image and asks for a smaller original file. This avoids introducing compression artifacts into OCR evidence.

The original `POST /api/analyze` route remains available for local development, manual-text demonstrations and backwards-compatible backend testing.

## Verification before deployment

From the repository root on Windows:

```powershell
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify\verify-all.ps1
```

For the difficult referenced-MRP regression:

```powershell
pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify\verify-referenced-mrp.ps1
```

## Demo images

Use the files in the root `samples/` directory as the known-good v0.8 prototype uploads.

## If the Vercel OCR function cannot initialize

The most likely hosted-runtime bottlenecks are PP-OCRv6 model download/cold-start time, function bundle size, or the Hobby project's available memory. Check the backend deployment and runtime logs first. Do not change the OCR model or silently lower image quality merely to make the deployment pass; preserve the verified OCR contract and move only the backend hosting layer if necessary.
