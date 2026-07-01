// SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/**
 * Resolution of the backend `artifact://<id>` scheme to loadable URLs.
 *
 * The deep-research report stores image references as `![caption](artifact://<artifact_id>)`.
 * Each render surface rewrites that scheme to a real source at its own edge; this module is
 * the single source of truth for building the same-origin content URL used by the UI.
 */

export const ARTIFACT_SCHEME = 'artifact://'

/** True when a markdown image `src` uses the durable `artifact://<id>` scheme. */
export const isArtifactRef = (src: string | undefined): src is string =>
  typeof src === 'string' && src.startsWith(ARTIFACT_SCHEME)

/** Extract the artifact id from an `artifact://<id>` reference (trims any path/query noise). */
export const artifactIdFromRef = (src: string): string =>
  src.slice(ARTIFACT_SCHEME.length).trim()

/**
 * Build the same-origin proxy URL that streams an artifact's bytes.
 *
 * Returns the original `src` unchanged when it is not an `artifact://` ref or when the owning
 * `jobId` is unknown (so a bad ref degrades to a broken image rather than a wrong fetch).
 */
export const resolveArtifactUrl = (src: string | undefined, jobId?: string): string | undefined => {
  if (!isArtifactRef(src) || !jobId) return src
  const id = artifactIdFromRef(src)
  if (!id) return src
  return artifactContentPath(jobId, id)
}

// Single source of truth for the markdown image -> artifact ref pattern. `matchAll`
// clones the regex internally and `replace` resets lastIndex, so sharing this module-level
// instance across the helpers below is safe.
const ARTIFACT_IMG_RE = /!\[([^\]]*)\]\(artifact:\/\/([^)]+)\)/g

/** Build the relative same-origin content path for an artifact (no leading origin). */
export const artifactContentPath = (jobId: string, artifactId: string): string =>
  `/api/jobs/async/job/${encodeURIComponent(jobId)}/artifacts/${encodeURIComponent(artifactId)}/content`

/**
 * Replace every `![alt](artifact://<id>)` image using `replacer`. Returning `null` from the
 * replacer leaves the original token untouched. Shared by the UI/download rewrite and the
 * server-side PDF inliner so the matching rule lives in exactly one place.
 */
export const replaceArtifactImages = (
  markdown: string,
  replacer: (alt: string, artifactId: string) => string | null
): string =>
  markdown.replace(ARTIFACT_IMG_RE, (full, alt: string, id: string) => replacer(alt, id.trim()) ?? full)

/** Collect the unique artifact ids referenced as images in the markdown. */
export const extractArtifactIds = (markdown: string): string[] => {
  const ids = new Set<string>()
  for (const match of markdown.matchAll(ARTIFACT_IMG_RE)) ids.add(match[2].trim())
  return Array.from(ids)
}

/**
 * Rewrite every `![alt](artifact://<id>)` in a markdown string to a content URL.
 *
 * @param markdown report markdown that may contain `artifact://` image refs
 * @param jobId owning job id used to build the content URL
 * @param origin optional absolute origin (e.g. `https://host`); when provided the URL is
 *   absolute so the markdown renders outside the app (downloaded `.md`). Defaults to a
 *   same-origin relative URL.
 */
export const rewriteArtifactRefs = (markdown: string, jobId?: string, origin = ''): string => {
  if (!jobId) return markdown
  return replaceArtifactImages(markdown, (alt, id) => `![${alt}](${origin}${artifactContentPath(jobId, id)})`)
}
