/**
 * The tau app's public downloads (roadmap 190), served from the private R2 bucket bound as
 * `DOWNLOADS` (`tau-downloads`), so they do not depend on the repository being public:
 *
 *   GET|HEAD /download/tau.dmg                     the latest release's disk image
 *   GET|HEAD /download/latest.json                 the Tauri updater's manifest of that release
 *   GET|HEAD /download/tau.app.tar.gz              the latest release's updater archive
 *   GET|HEAD /download/v<version>/tau.dmg          one release's files; <version> is semver
 *   GET|HEAD /download/v<version>/tau.app.tar.gz   (0.5.0, 0.5.0-rc1)
 *
 * The object key is the path after `/download/`. CI (.github/workflows/app.yml) uploads a
 * release's versioned files first and the unversioned ones last, so `latest.json`, whose URL
 * names the versioned archive, never points at a file that is not there yet. Pre-releases get
 * only their versioned files.
 *
 * The bucket is private and never listed: only the names above are read, a version must be
 * semver, and the path is matched as it arrives (still percent-encoded), so no other key can
 * be asked for. `/download` itself is the download page; `/download/` redirects to it. Every
 * other path under `/download/` is not a download: `serveDownload` returns null for it, and
 * the caller answers it like any unknown path.
 *
 * Answers: ETag and Last-Modified from R2, `If-None-Match` (and `If-Modified-Since` without
 * it) → 304, one byte range → 206 with `Content-Range` (honouring `If-Range`), an
 * unsatisfiable range → 416. `latest.json` and the unversioned files may change with the next
 * release, so they are cached for five minutes; a versioned file never changes. Without the
 * binding every download is `503 {"error": "downloads_unavailable"}`, and a file the bucket
 * does not have (yet) is `404 {"error": "not_found"}`.
 *
 * No static file lives under `/download/`, so these paths always reach the Worker. Contract: docs/reference/tau-universe.md §2, "App downloads".
 */

import { error, methodNotAllowed } from "./http";

/** The bindings this module reads; a universe without the bucket answers 503. */
export interface DownloadsEnv {
  DOWNLOADS?: R2Bucket;
}

export const DOWNLOAD_PREFIX = "/download/";

/** The latest release's files, at `/download/<name>`. */
export const LATEST_FILES: ReadonlySet<string> = new Set([
  "tau.dmg",
  "tau.app.tar.gz",
  "latest.json",
]);

/** One release's files, at `/download/v<version>/<name>`. */
export const VERSIONED_FILES: ReadonlySet<string> = new Set(["tau.dmg", "tau.app.tar.gz"]);

/**
 * A release version: Semantic Versioning 2.0.0 without build metadata (CI turns tau-core's
 * 0.5.0rc1 into 0.5.0-rc1). No leading zeros, no empty identifiers.
 */
const NUMBER = "(?:0|[1-9][0-9]*)";
const PRERELEASE_ID = `(?:${NUMBER}|[0-9]*[A-Za-z-][0-9A-Za-z-]*)`;
export const SEMVER = new RegExp(
  `^${NUMBER}\\.${NUMBER}\\.${NUMBER}(?:-${PRERELEASE_ID}(?:\\.${PRERELEASE_ID})*)?$`,
);

/** Longer versions are refused before the pattern runs. */
const MAX_VERSION = 64;

const CONTENT_TYPES: Readonly<Record<string, string>> = {
  "tau.dmg": "application/x-apple-diskimage",
  "tau.app.tar.gz": "application/gzip",
  "latest.json": "application/json",
};

/** `latest.json` and the unversioned files: the next release replaces them. */
export const LATEST_CACHE = "public, max-age=300";
/** A release's own files never change. */
export const VERSIONED_CACHE = "public, max-age=31536000, immutable";

/** A download path: its R2 key and file name. */
export interface Download {
  key: string;
  file: string;
  versioned: boolean;
}

/** The download a path names, or null when it names none (only exact allowlisted names). */
export function downloadOf(path: string): Download | null {
  if (!path.startsWith(DOWNLOAD_PREFIX)) return null;
  const parts = path.slice(DOWNLOAD_PREFIX.length).split("/");
  if (parts.length === 1) {
    const file = parts[0]!;
    return LATEST_FILES.has(file) ? { key: file, file, versioned: false } : null;
  }
  if (parts.length !== 2) return null;
  const [dir, file] = parts as [string, string];
  if (!VERSIONED_FILES.has(file) || !dir.startsWith("v")) return null;
  const version = dir.slice(1);
  if (version.length > MAX_VERSION || !SEMVER.test(version)) return null;
  return { key: `${dir}/${file}`, file, versioned: true };
}

/**
 * A request for one of the app's downloads, or null when the path is not one (the caller then
 * goes on with its own routing). Call it for paths under `/download/`.
 */
export async function serveDownload(
  request: Request,
  env: DownloadsEnv,
  url: URL,
): Promise<Response | null> {
  if (url.pathname === DOWNLOAD_PREFIX) {
    return new Response(null, { status: 301, headers: { location: `/download${url.search}` } });
  }
  const download = downloadOf(url.pathname);
  if (download === null) return null;
  if (request.method !== "GET" && request.method !== "HEAD") {
    return methodNotAllowed(["GET", "HEAD"]);
  }
  const bucket = env.DOWNLOADS;
  if (bucket === undefined) return noStore(error(503, "downloads_unavailable"));

  // A release upload can replace an unversioned file between the two reads; the second
  // attempt then reads the new one.
  for (let attempt = 0; attempt < 2; attempt++) {
    const object = await bucket.head(download.key);
    if (object === null) return noStore(error(404, "not_found"));
    if (notModified(request.headers, object)) {
      return new Response(null, { status: 304, headers: validators(download, object) });
    }
    const headers = headersOf(download, object);

    // Range applies to GET only.
    let range: ByteRange | "unsatisfiable" | null = null;
    if (request.method === "GET" && rangeStillValid(request.headers.get("if-range"), object)) {
      range = byteRange(request.headers.get("range"), object.size);
    }
    if (range === "unsatisfiable") {
      const unsatisfiable = validators(download, object);
      unsatisfiable.set("content-range", `bytes */${object.size}`);
      return new Response(null, { status: 416, headers: unsatisfiable });
    }
    if (request.method === "HEAD") {
      headers.set("content-length", String(object.size));
      return new Response(null, { status: 200, headers });
    }

    const body = await bucket.get(download.key, {
      onlyIf: { etagMatches: object.etag },
      ...(range === null ? {} : { range }),
    });
    if (body === null) return noStore(error(404, "not_found"));
    if (!("body" in body)) continue;
    if (range === null) {
      headers.set("content-length", String(object.size));
      return new Response(body.body, { status: 200, headers });
    }
    const last = range.offset + range.length - 1;
    headers.set("content-range", `bytes ${range.offset}-${last}/${object.size}`);
    headers.set("content-length", String(range.length));
    return new Response(body.body, { status: 206, headers });
  }
  return noStore(error(503, "downloads_unavailable"));
}

function noStore(response: Response): Response {
  response.headers.set("cache-control", "no-store");
  return response;
}

/** What every answer about a file carries, a 304 included: its validators and caching. */
function validators(download: Download, object: R2Object): Headers {
  return new Headers({
    "cache-control": download.versioned ? VERSIONED_CACHE : LATEST_CACHE,
    etag: object.httpEtag,
    "last-modified": object.uploaded.toUTCString(),
  });
}

/** The headers of a 200 or 206: the validators plus the file's type. */
function headersOf(download: Download, object: R2Object): Headers {
  const headers = validators(download, object);
  headers.set("content-type", CONTENT_TYPES[download.file]!);
  headers.set("accept-ranges", "bytes");
  if (download.file === "tau.dmg") {
    headers.set("content-disposition", 'attachment; filename="tau.dmg"');
  }
  return headers;
}

/** An entity tag without its weak prefix, for the weak comparison of If-None-Match. */
function opaque(tag: string): string {
  return tag.startsWith("W/") ? tag.slice(2) : tag;
}

/** Whether the client's copy is current: If-None-Match, or If-Modified-Since without it. */
export function notModified(headers: Headers, object: R2Object): boolean {
  const ifNoneMatch = headers.get("if-none-match");
  if (ifNoneMatch !== null) {
    const tags = ifNoneMatch.match(/\*|(?:W\/)?"[^"]*"/g) ?? [];
    return tags.some((tag) => tag === "*" || opaque(tag) === opaque(object.httpEtag));
  }
  const ifModifiedSince = headers.get("if-modified-since");
  if (ifModifiedSince === null) return false;
  const since = Date.parse(ifModifiedSince);
  return Number.isFinite(since) && seconds(object.uploaded.getTime()) <= seconds(since);
}

function seconds(ms: number): number {
  return Math.floor(ms / 1000);
}

/**
 * Whether a Range still applies: no If-Range, or one naming this very file (its strong
 * ETag, or its upload time). Otherwise the client's partial copy is of an older file, and it
 * gets the whole new one.
 */
export function rangeStillValid(ifRange: string | null, object: R2Object): boolean {
  if (ifRange === null) return true;
  const value = ifRange.trim();
  if (value.startsWith('"')) return value === object.httpEtag;
  if (value.startsWith("W/")) return false;
  const date = Date.parse(value);
  return Number.isFinite(date) && seconds(date) === seconds(object.uploaded.getTime());
}

export interface ByteRange {
  offset: number;
  length: number;
}

/**
 * The single byte range a Range header asks for in a file of `size` bytes: null for the whole
 * file (no header, another unit, several ranges, or a malformed one, all of which may be
 * ignored), "unsatisfiable" when it starts past the end.
 */
export function byteRange(header: string | null, size: number): ByteRange | "unsatisfiable" | null {
  if (header === null) return null;
  const match = /^bytes=([0-9]{0,15})-([0-9]{0,15})$/i.exec(header.trim());
  if (match === null) return null;
  const first = match[1]!;
  const last = match[2]!;
  if (first === "") {
    if (last === "") return null;
    const suffix = Number(last);
    if (suffix === 0 || size === 0) return "unsatisfiable";
    const length = Math.min(suffix, size);
    return { offset: size - length, length };
  }
  const offset = Number(first);
  if (last !== "" && Number(last) < offset) return null;
  if (offset >= size) return "unsatisfiable";
  const end = last === "" ? size - 1 : Math.min(Number(last), size - 1);
  return { offset, length: end - offset + 1 };
}
