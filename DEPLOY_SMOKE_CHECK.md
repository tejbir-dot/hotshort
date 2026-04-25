# Vercel Smoke Check

Run these checks after each preview or production deploy.

## Build Validation

1. Run `vercel pull --yes --environment preview`
2. Run `vercel build --yes`
3. Confirm the build is not a near-instant no-op and `.vercel/output` contains a Python function

## URL Validation

1. Deploy a preview build
2. Run `python tools/vercel_smoke_check.py https://<deployment-url>`
3. Repeat against `https://hotshort.vercel.app`

## Expected Results

- `/` returns application HTML
- `/health` returns `ok`
- `/auth/login` loads successfully
- `/static/style.css` returns successfully and does not return a Vercel platform `NOT_FOUND`
