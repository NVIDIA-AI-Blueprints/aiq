# NVIDIA AI-Q Blueprint UI

A modern research assistant interface built with Next.js, React, TypeScript, TailwindCSS, and NVIDIA KUI Foundations.

## Overview

The AI-Q Blueprint UI provides an accessible, feature-rich frontend for the AI-Q backend. It features:

- **Next.js** with App Router and Turbopack
- **React** with TypeScript (strict mode)
- **[KUI Foundations](https://www.npmjs.com/package/@nvidia/foundations-react-core)** NVIDIA design components
- **TailwindCSS** for layout utilities
- **Adapter-based architecture** for clean separation of concerns
- **Optional OAuth authentication** (disabled by default)

## Prerequisites

- Node.js
- npm
- AI-Q Blueprint running (default: `http://localhost:8000`)

## Quick Start

### 1. Install Dependencies

```bash
npm install
```

### 2. Configure Environment

Review the `.env` config in the project root to ensure values are set correctly for local development.

Key variables for local development:

```bash
# Backend URL (must match where your backend is running)
BACKEND_URL=http://localhost:8000

# Skip authentication for local development (uses Default User)
REQUIRE_AUTH=false

# File upload settings (should match backend limits)
FILE_UPLOAD_ACCEPTED_TYPES=.pdf,.txt,.md,.docx,.pptx
FILE_UPLOAD_MAX_SIZE_MB=100
FILE_UPLOAD_MAX_FILE_COUNT=10
FILE_EXPIRATION_CHECK_INTERVAL_HOURS=24
```

See `.env.example` for the full list of available frontend variables including authentication and file upload configuration.


### 3. Start Servers

#### Running the Services

**Start e2e** (from monorepo root)
```bash
cd ../../
./scripts/start_e2e.sh
```
>**NOTE:** For UI development it may be more useful to use `./scripts/start_server_in_debug_mode.sh` with `npm run dev` in separate terminals.

#### Separate terminal env setup

When running the backend with `./scripts/start_server_in_debug_mode.sh` and the UI with `npm run dev` in a separate terminal, load the root env file in the UI terminal first:

```bash
set -a; source ../../deploy/.env; set +a
npm run dev
```

**URLs:**

- Frontend: http://localhost:3000
- Backend: http://localhost:8000

## NPM Scripts

| Script               | Description                                            |
| -------------------- | ------------------------------------------------------ |
| `npm run dev`        | Start gateway + Next.js dev server (with HMR)          |
| `npm run build`      | Build for production                                   |
| `npm run start`      | Start production server (gateway with WebSocket proxy) |
| `npm run lint`       | Run ESLint                                             |
| `npm run lint:fix`   | Run ESLint with auto-fix                               |
| `npm run format`     | Format code with Prettier                              |
| `npm run type-check` | Run TypeScript type checking                           |
| `npm run test`       | Run tests once (Vitest)                                |
| `npm run test:watch` | Run tests in watch mode                                |
| `npm run test:ci`    | Run tests with coverage                                |

## Project Structure

```
src/
├── adapters/           # External interface boundaries
│   ├── api/            # Backend API clients (chat, documents, websocket, deep-research)
│   ├── auth/           # NextAuth configuration, session, and types
│   ├── datadog/        # Real User Monitoring integration (optional)
│   └── ui/             # KUI component re-exports, icons, logo
├── app/                # Next.js App Router pages and API routes
│   ├── api/            # Route handlers (auth, chat, health, proxy, jobs)
│   └── auth/           # Sign-in and error pages
├── features/           # Business logic modules
│   ├── chat/           # Chat functionality (components, hooks, store, types)
│   ├── documents/      # File upload, validation, and persistence
│   └── layout/         # App layout components (panels, tabs, navigation)
├── hooks/              # Shared React hooks (PDF download, session URL)
├── lib/                # Utilities (PDF generation)
├── mocks/              # MSW mock handlers and database for testing
├── pages/              # API routes (PDF generation)
├── shared/             # Shared components, config, context, hooks, and utilities
│   ├── components/     # MarkdownRenderer, StarfieldAnimation
│   ├── config/         # File upload configuration
│   ├── context/        # AppConfigContext
│   ├── hooks/          # Backend health check hook
│   └── utils/          # Shared utilities (time formatting)
├── styles/             # KUI-generated CSS and safelist
├── test-utils/         # Test helper utilities
└── utils/              # General utilities (markdown download)
```

## Architecture

The UI acts as a **gateway/proxy** between the browser and backend:

- All HTTP API requests go through Next.js API routes (`/api/*`)
- WebSocket connections are proxied through the custom server (`/websocket`)
- Backend URL is runtime configurable via `BACKEND_URL` environment variable

This architecture ensures the backend doesn't need public exposure - only the UI container needs ingress. See the [Docker Deployment](#docker-deployment) section for details.

## Session Storage Management

The AI-Q UI uses localStorage to persist chat sessions across page refreshes. To prevent quota exceeded errors and ensure optimal performance, the app implements automatic storage management.

### Storage Limits

- **localStorage Quota**: ~5MB (browser-dependent)
- **Warning Threshold**: 4MB (80% of quota)
- **Target After Cleanup**: <3MB (60% of quota)

### What Gets Stored

Sessions are stored with optimized data to minimize storage usage:

**Stored (Essential for UI):**
- Session metadata (id, title, timestamps)
- Message content and timestamps
- Thinking steps (for ChatThinking display)
- Plan messages (cannot be refetched from backend)
- Job IDs for deep research restoration

**Not Stored (Fetched from backend on demand):**
- Report content (loaded via API)
- Citations, tasks, tool calls (replayed from SSE stream)
- Agent traces and file artifacts

### Automatic Cleanup

When creating a new session, if storage exceeds 4MB:

1. **Auto-cleanup triggers** - Deletes oldest sessions (by `updatedAt` timestamp)
2. **Current session protected** - Never deletes the active session
3. **Stops at 3MB** - Cleanup continues until storage is healthy
4. **Console warnings** - Logs deleted sessions for debugging

### Manual Cleanup

To manually clear sessions:
1. Open SessionsPanel (left sidebar)
2. Click "Delete All Sessions" button
3. Or delete individual sessions one at a time


### How Research Data Loading Works

When you reopen a session after a page refresh:

1. **ChatArea** - Displays immediately (messages, thinking steps loaded from localStorage)
2. **PlanTab** - Displays immediately (plan messages loaded from localStorage)
3. **Report/Tasks/Citations tabs** - Shows loading spinner, then fetches data from backend

The lazy loading is automatic and seamless - you don't need to do anything special.



## Docker Deployment

### Build

From the **UI directory** (`frontends/ui/`):

```bash
docker build -t aiq-blueprint-ui:latest .
```

### Run

**Without authentication (default):**

```bash
docker run -p 3000:3000 \
  -e BACKEND_URL=http://localhost:8000 \
  -e REQUIRE_AUTH=false \
  aiq-blueprint-ui:latest
```

**With OAuth authentication:**

```bash
docker run -p 3000:3000 \
  -e BACKEND_URL=http://localhost:8000 \
  -e REQUIRE_AUTH=true \
  -e NEXTAUTH_SECRET=$(openssl rand -base64 32) \
  -e NEXTAUTH_URL=https://your-domain.com \
  -e OAUTH_CLIENT_ID=your-client-id \
  -e OAUTH_CLIENT_SECRET=your-client-secret \
  -e OAUTH_ISSUER=https://your-oidc-provider.com \
  aiq-blueprint-ui:latest
```

### Docker Compose Example

```yaml
services:
  frontend:
    image: aiq-blueprint-ui:latest
    environment:
      # Backend
      - BACKEND_URL=http://backend:8000

      # Authentication (auth is disabled by default)
      - REQUIRE_AUTH=${REQUIRE_AUTH:-false}
      - NEXTAUTH_SECRET=${NEXTAUTH_SECRET}
      - NEXTAUTH_URL=${NEXTAUTH_URL:-http://localhost:3000}

      # OAuth (required when REQUIRE_AUTH=true)
      - OAUTH_CLIENT_ID=${OAUTH_CLIENT_ID}
      - OAUTH_CLIENT_SECRET=${OAUTH_CLIENT_SECRET}
      - OAUTH_ISSUER=${OAUTH_ISSUER}
    ports:
      - "3000:3000"
    depends_on:
      - backend
```

### Networking

#### Connecting to Host Services

When running in Docker and connecting to services on the host machine:

- **macOS/Windows:** Use `host.docker.internal`
- **Linux:** Use `--network=host` or configure Docker networking

```bash
# Connect to backend running on host
docker run -p 3000:3000 \
  -e BACKEND_URL=http://host.docker.internal:8000 \
  -e REQUIRE_AUTH=false \
  aiq-blueprint-ui:latest
```

#### Docker Network

When using docker-compose or custom networks, use service names:

```bash
-e BACKEND_URL=http://backend:8000
```

### Health Check

The container includes a health check that polls the root endpoint:

```
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3
    CMD curl -f http://localhost:3000/ || exit 1
```

## Environment Variables

All environment variables are **runtime configurable** - no container rebuild needed.

### Backend

| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_URL` | `http://localhost:8000` | Backend API URL |

### Authentication

| Variable | Default | Description |
|----------|---------|-------------|
| `REQUIRE_AUTH` | `false` | Set to `true` to require OAuth login |
| `NEXTAUTH_SECRET` | - | Session encryption secret (required if auth enabled) |
| `NEXTAUTH_URL` | - | Public URL where app is hosted (required if auth enabled) |

> **Cookie Security:** `NEXTAUTH_URL` determines cookie security:
> - `http://...` -> non-secure cookies (local dev over HTTP)
> - `https://...` -> secure cookies (production over HTTPS)

### OAuth (required when `REQUIRE_AUTH=true`)

| Variable | Default | Description |
|----------|---------|-------------|
| `OAUTH_CLIENT_ID` | - | OAuth client ID from your OIDC provider |
| `OAUTH_CLIENT_SECRET` | - | OAuth client secret |
| `OAUTH_ISSUER` | - | OIDC issuer URL (enables auto-discovery of endpoints) |

> **Note:** When `OAUTH_ISSUER` is set, the app uses OIDC auto-discovery to resolve authorization, token, and userinfo endpoints automatically. No additional endpoint URLs are needed for standard OIDC providers.


## API Communication

The UI supports two communication patterns with the backend:

### HTTP Streaming (SSE)

OpenAI-compatible chat completions via `/chat/stream`:

```typescript
import { streamChat } from '@/adapters/api'

await streamChat(
  { messages, sessionId, workflowId },
  {
    onChunk: (content) => console.log(content),
    onComplete: () => console.log('Done'),
    onError: (error) => console.error(error),
  }
)
```

### WebSocket

Custom protocol for real-time agent communication:

```typescript
import { createWebSocketClient } from '@/adapters/api'

const ws = createWebSocketClient({
  sessionId: 'abc123',
  workflowId: 'researcher',
  callbacks: {
    onAgentText: (content, isFinal) => {},
    onStatus: (status, message) => {},
    onToolCall: (name, input, output) => {},
    onError: (code, message) => {},
  },
})

ws.connect()
ws.sendMessage('Hello!')
```

## Authentication

Authentication is **disabled by default**. All users are assigned a "Default User" identity with no login required.

To enable OAuth authentication:

1. Set `REQUIRE_AUTH=true`
2. Configure your OIDC provider credentials:

```bash
# .env
REQUIRE_AUTH=true
NEXTAUTH_SECRET=<generate-with-openssl-rand-base64-32>
NEXTAUTH_URL=http://localhost:3000
OAUTH_CLIENT_ID=<your-client-id>
OAUTH_CLIENT_SECRET=<your-client-secret>
OAUTH_ISSUER=<your-oidc-issuer-url>
```

### Using the Auth Hook

```typescript
import { useAuth } from '@/adapters/auth'

const MyComponent = () => {
  const { user, isAuthenticated, isLoading, idToken, signIn, signOut } = useAuth()

  if (isLoading) return <Spinner />
  if (!isAuthenticated) return <Button onClick={signIn}>Sign In</Button>

  // Use idToken for backend API calls
  await fetch('/api/data', {
    headers: { 'Authorization': `Bearer ${idToken}` }
  })

  return <Text>Welcome, {user?.name}</Text>
}
```

>**NOTE:** Above Authentication docs are reference only and implementation depends on environment specifics. 


## Development

### Adding a New Feature

1. Create a directory under `src/features/[feature-name]/`
2. Add subdirectories: `components/`, `hooks/`
3. Create `types.ts` for feature-specific types
4. Create `store.ts` for Zustand state (if needed)

### Adding a New API Endpoint

1. Add Zod schema in `src/adapters/api/schemas.ts`
2. Create client function in appropriate adapter file
3. Export from `src/adapters/api/index.ts`

## Import Rules

Features should **never** import external packages directly. All external calls go through adapters:

```typescript
// Correct
import { Button, Flex, Text } from '@/adapters/ui'
import { streamChat } from '@/adapters/api'
import { useSession } from '@/adapters/auth'

// Wrong
import { Button } from '@nvidia/foundations-react-core'
import { signIn } from 'next-auth/react'
```


## Styling

This project uses KUI Foundations for styling:

- Use KUI component props for visual styling (`kind`, `size`, etc.)
- Use Tailwind only for layout (`flex`, `grid`, `mt-4`, `px-6`)
- Never override KUI colors with Tailwind
- Dark mode is handled automatically by ThemeProvider

```tsx
// Correct
<Flex className="mt-4 px-6">
  <Button kind="primary" size="medium">Submit</Button>
</Flex>

// Wrong
<Button className="bg-blue-500 text-white">Submit</Button>
```

## Testing

The project uses **Vitest** with **Testing Library** and **MSW** (Mock Service Worker):

```bash
# Run tests once
npm run test

# Run tests in watch mode
npm run test:watch

# Run tests with coverage
npm run test:ci
```

- **Vitest** -- Test runner with coverage via `@vitest/coverage-v8`
- **Testing Library** -- `@testing-library/react` and `@testing-library/user-event` for component testing
- **MSW** -- Mock Service Worker for API mocking in tests (handlers in `src/mocks/`)
- **happy-dom** -- DOM environment for tests

Test utilities are in `src/test-utils/` and MSW mock handlers/database are in `src/mocks/`.

## Troubleshooting

### Backend connection fails

1. Verify backend is running: `curl http://localhost:8000/docs`
2. Check `BACKEND_URL` in `.env.local`
3. Check browser console for CORS errors


### Port already in use

Kill existing processes:

```bash
lsof -ti :8000 | xargs kill -9  # Backend
lsof -ti :3000 | xargs kill -9  # Frontend
```

### Docker: Cannot connect to backend

- Use `host.docker.internal` instead of `localhost` to reach host machine services
- Ensure backend is bound to `0.0.0.0`, not just `127.0.0.1`
- Check Docker network configuration if using docker-compose

