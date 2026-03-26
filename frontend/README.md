# Healthcare Frontend (React + Vite)

Responsive frontend for PDF-based healthcare report analysis and user health records.

## Features

- Login and signup flows with email/password validation
- Protected routes for dashboard and report upload pages
- Dedicated pages for Dashboard, Health Records, Upload, and Profile
- PDF upload with validation (PDF-only + size limit)
- Extraction preview and async report status polling
- Dashboard for processed reports and structured parameter display
- Reusable API layer and modular folder architecture
- Loading states and toast notifications

## Folder Structure

src/
- components/
- pages/
- services/
- hooks/
- utils/
- assets/
- styles/
- context/

## Setup

1. Copy `.env.example` to `.env` and update values as needed.
2. Install dependencies.
3. Run development server.

```bash
npm install
npm run dev
```

## Backend Integration

The frontend is configured for these backend endpoints:

- `POST /api/v1/upload_pdf_report`
- `POST /api/v1/pdf_to_lab_json`
- `GET /api/v1/lab_parameters/status/{txn_id}`

Authentication endpoints are configurable with environment variables:

- `VITE_AUTH_LOGIN_ENDPOINT`
- `VITE_AUTH_SIGNUP_ENDPOINT`
- `VITE_AUTH_ME_ENDPOINT`
- `VITE_AUTH_LOGOUT_ENDPOINT`

If these auth endpoints are not available yet, set `VITE_ENABLE_LOCAL_AUTH_FALLBACK=true` to keep the frontend usable with local session fallback.
By default `.env.example` keeps this fallback off for production-like authentication behavior.

Additional backend endpoint used by records/dashboard:

- `GET /api/v1/users/{user_id}/transactions`

## Notes on Token Security

- API client uses `withCredentials: true`, so HTTP-only cookie sessions are supported when backend auth is cookie-based.
- If backend returns a token directly, frontend stores it in session storage as fallback.

## Suggested Minimal Backend Enhancement (Optional)

For richer server-side dashboard history across devices, add one endpoint:

- `GET /api/v1/user/{user_id}/transactions`

This is optional because current UI already reads and refreshes transaction statuses by stored transaction IDs.
