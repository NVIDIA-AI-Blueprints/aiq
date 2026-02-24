# NVIDIA AI-Q Blueprint UI

A modern research assistant interface built with Next.js 16+, React 18+, TypeScript, TailwindCSS, and NVIDIA KUI Foundations.

## Overview

The AI-Q Blueprint UI provides an accessible, feature-rich frontend for the AI-Q backend. It features:

- **Next.js** with App Router and Turbopack
- **React** with TypeScript (strict mode)
- **[KUI Foundations](https://www.npmjs.com/package/@nvidia/foundations-react-core)** NVIDIA design components
- **TailwindCSS** for layout utilities
- **Adapter-based architecture** for clean separation of concerns
- **Optional OAuth authentication** (disabled by default)

## Prerequisites

- Node.js 18+
- npm or pnpm
- AI-Q Blueprint running (default: `http://localhost:8000`)

## Quick Start

### 1. Install Dependencies

```bash
npm install
```

### 2. Configure Environment

Review `.env.local` configs are in the project root.


### 3. Start Servers

#### Running the Services

**Start e2e** (from monorepo root)
```bash
cd ../../
./scripts/start_e2e.sh
```
>**NOTE:** For UI development it may be more useful to use `./scripts/start_server_in_debug_mode.sh` with `npm run dev` in separate terminals. 

**URLs:**

- Frontend: http://localhost:3000
- Backend: http://localhost:8000


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

This optimization reduces storage usage by ~96% per session, preventing quota errors while maintaining full functionality.

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

### Architecture

The UI container acts as a **full proxy** between the browser and backend:

```
+---------+     +-------------------------------+     +---------+
| Browser |---->|         UI Container          |---->| Backend |
|         |     |  (HTTP + WebSocket Proxy)     |     |         |
+---------+     +-------------------------------+     +---------+
                         |
                    Ingress only
```

**All traffic flows through the UI container:**
- HTTP API requests -> `/api/*` routes -> Backend
- WebSocket connections -> `/websocket` proxy -> Backend


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

## Project Structure

```
src/
├── adapters/           # External interface boundaries
│   ├── api/            # Backend API clients (chat, websocket)
│   ├── auth/           # NextAuth configuration and hooks
│   └── ui/             # KUI component re-exports
├── features/           # Business logic modules
│   ├── chat/           # Chat functionality (components, hooks, store, types)
│   ├── documents/      # File upload and management
│   ├── layout/         # App layout components (panels, tabs, navigation)
│   └── auth/           # Authentication components
├── app/                # Next.js App Router pages
├── shared/             # Internal utilities and types
└── tests/              # Test files
```

### Import Rules

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

## Available Scripts

### NPM Scripts

| Script               | Description                                              |
| -------------------- | -------------------------------------------------------- |
| `npm run dev`        | Start gateway + Next.js dev server (with HMR)            |
| `npm run build`      | Build for production                                     |
| `npm run start`      | Start production server (gateway with WebSocket proxy)   |
| `npm run lint`       | Run ESLint                                               |
| `npm run format`     | Format code with Prettier                                |
| `npm run type-check` | Run TypeScript type checking                             |

## Architecture

The UI acts as a **gateway/proxy** between the browser and backend:

- All HTTP API requests go through Next.js API routes (`/api/*`)
- WebSocket connections are proxied through the custom server (`/websocket`)
- Backend URL is runtime configurable via `BACKEND_URL` environment variable

This architecture ensures the backend doesn't need public exposure - only the UI container needs ingress. See the [Docker Deployment](#docker-deployment) section for details.

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
# .env.local
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

