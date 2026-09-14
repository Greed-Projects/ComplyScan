# Vercel Deployment

PackCheck-AI v0.8 uses Vercel for the Next.js frontend and a separate Python host for the FastAPI OCR backend.

## Frontend on Vercel

Import this GitHub repository into Vercel and configure:

- **Root Directory:** `frontend`
- **Framework Preset:** Next.js
- **Build Command:** use the package default (`npm run build`)
- **Environment Variable:** `NEXT_PUBLIC_API_URL=https://<your-backend-host>`

The frontend reads `NEXT_PUBLIC_API_URL` at build time. Redeploy after changing it.

## Backend

Deploy `backend/` to a Python service capable of running the existing FastAPI + PaddleOCR/ONNX Runtime/OpenCV stack.

Set:

```text
PACKCHECK_ALLOWED_ORIGINS=https://<your-vercel-domain>
```

Multiple origins can be comma-separated. Local development origins remain enabled.

## Why the OCR API is not proxied through a Vercel Function

The current prototype accepts images larger than Vercel's normal function request-body limit. Keeping uploads direct from the browser to the Python backend preserves the existing PackCheck upload contract and avoids an unnecessary proxy hop.

## Demo images

Use the files in the root `samples/` directory as the known-good v0.8 prototype uploads.
