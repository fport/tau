/**
 * The app's downloads (src/downloads.ts, roadmap 190), called directly with a fake R2
 * bucket: the allowlist, the headers, HEAD, 304, 206/416, the missing binding and object,
 * and that nothing outside the allowlist ever reaches the bucket.
 */

import { describe, expect, it } from "vitest";
import {
  byteRange,
  downloadOf,
  type DownloadsEnv,
  LATEST_CACHE,
  SEMVER,
  serveDownload,
  VERSIONED_CACHE,
} from "../src/downloads";
import { isForwarded, isReservedName, pageRoute } from "../src/routes";

const HOST = "https://universe.example";
const UPLOADED = new Date("2026-10-01T12:00:00Z");

interface Stored {
  bytes: Uint8Array;
  etag: string;
  uploaded: Date;
}

/** The R2 calls the module may make: `head` and `get`; anything else fails the test. */
class FakeBucket {
  readonly objects = new Map<string, Stored>();
  readonly calls: string[] = [];
  /** Runs once after the next `head`, e.g. to replace the object in between. */
  afterHead: (() => void) | null = null;

  put(key: string, content: string | Uint8Array, etag: string, uploaded = UPLOADED): void {
    const bytes = typeof content === "string" ? new TextEncoder().encode(content) : content;
    this.objects.set(key, { bytes, etag, uploaded });
  }

  private meta(key: string, stored: Stored) {
    return {
      key,
      version: "v1",
      size: stored.bytes.byteLength,
      etag: stored.etag,
      httpEtag: `"${stored.etag}"`,
      checksums: {},
      uploaded: stored.uploaded,
      httpMetadata: {},
      customMetadata: {},
      storageClass: "Standard",
      writeHttpMetadata: () => undefined,
    };
  }

  async head(key: string) {
    this.calls.push(`head ${key}`);
    const stored = this.objects.get(key);
    const after = this.afterHead;
    this.afterHead = null;
    after?.();
    return stored === undefined ? null : this.meta(key, stored);
  }

  async get(key: string, options?: R2GetOptions) {
    const range = options?.range as { offset: number; length: number } | undefined;
    const asked = range === undefined ? "" : ` ${range.offset}+${range.length}`;
    this.calls.push(`get ${key}${asked}`);
    const stored = this.objects.get(key);
    if (stored === undefined) return null;
    const onlyIf = options?.onlyIf as R2Conditional | undefined;
    if (onlyIf?.etagMatches !== undefined && onlyIf.etagMatches !== stored.etag) {
      return this.meta(key, stored);
    }
    const bytes =
      range === undefined
        ? stored.bytes
        : stored.bytes.slice(range.offset, range.offset + range.length);
    return { ...this.meta(key, stored), body: new Response(bytes).body };
  }

  list(): never {
    throw new Error("the downloads bucket is never listed");
  }
}

const DMG = "dmg-bytes-0123456789"; // 20 bytes
const ARCHIVE = "tar-gz-bytes";
const MANIFEST = JSON.stringify({
  version: "0.5.0",
  platforms: {
    "darwin-aarch64": {
      signature: "sig",
      url: "https://tau.getporti.com/download/v0.5.0/tau.app.tar.gz",
    },
  },
});

function bucketWithRelease(): FakeBucket {
  const bucket = new FakeBucket();
  bucket.put("v0.5.0/tau.dmg", DMG, "dmg-v050");
  bucket.put("v0.5.0/tau.app.tar.gz", ARCHIVE, "tgz-v050");
  bucket.put("tau.dmg", DMG, "dmg-latest");
  bucket.put("tau.app.tar.gz", ARCHIVE, "tgz-latest");
  bucket.put("latest.json", MANIFEST, "json-latest");
  return bucket;
}

function envWith(bucket: FakeBucket): DownloadsEnv {
  return { DOWNLOADS: bucket as unknown as R2Bucket };
}

function fetchDownload(
  env: DownloadsEnv,
  path: string,
  init?: RequestInit,
): Promise<Response | null> {
  const request = new Request(`${HOST}${path}`, init);
  return serveDownload(request, env, new URL(request.url));
}

/** A binary body as text (the fixtures are ASCII); `.text()` would warn about the type. */
async function bytesOf(res: Response): Promise<string> {
  return new TextDecoder().decode(await res.arrayBuffer());
}

/** A download's answer; fails the test when the module did not take the path. */
async function download(env: DownloadsEnv, path: string, init?: RequestInit): Promise<Response> {
  const res = await fetchDownload(env, path, init);
  expect(res, path).not.toBeNull();
  return res!;
}

describe("download paths", () => {
  it("map the allowlisted names to their R2 keys", () => {
    expect(downloadOf("/download/tau.dmg")).toEqual({
      key: "tau.dmg",
      file: "tau.dmg",
      versioned: false,
    });
    expect(downloadOf("/download/latest.json")?.key).toBe("latest.json");
    expect(downloadOf("/download/tau.app.tar.gz")?.key).toBe("tau.app.tar.gz");
    expect(downloadOf("/download/v0.5.0/tau.dmg")).toEqual({
      key: "v0.5.0/tau.dmg",
      file: "tau.dmg",
      versioned: true,
    });
    expect(downloadOf("/download/v0.5.0-rc1/tau.app.tar.gz")?.key).toBe(
      "v0.5.0-rc1/tau.app.tar.gz",
    );
    expect(downloadOf("/download/v1.0.0-alpha.1/tau.dmg")?.key).toBe("v1.0.0-alpha.1/tau.dmg");
  });

  it("refuse every other name, bad versions and traversal", () => {
    const refused = [
      "/download",
      "/download/",
      "/downloads/tau.dmg",
      "/tr/download/tau.dmg",
      "/download/tau.exe",
      "/download/TAU.DMG",
      "/download/tau.app.tar.gz.sig",
      "/download/latest.json/",
      "/download//tau.dmg",
      "/download/tau.dmg%00",
      "/download/v0.5.0/latest.json",
      "/download/v0.5.0/tau.app.tar.gz.sig",
      "/download/v0.5.0/",
      "/download/v0.5.0",
      "/download/0.5.0/tau.dmg",
      "/download/V0.5.0/tau.dmg",
      "/download/v0.5/tau.dmg",
      "/download/v01.5.0/tau.dmg",
      "/download/v0.5.0-/tau.dmg",
      "/download/v0.5.0-rc..1/tau.dmg",
      "/download/v0.5.0-01/tau.dmg",
      "/download/v0.5.0+build.1/tau.dmg",
      `/download/v0.5.0-${"a".repeat(60)}/tau.dmg`,
      "/download/v0.5.0/sub/tau.dmg",
      "/download/v0.5.0/../tau.dmg",
      "/download/../tau.dmg",
      "/download/..%2Ftau.dmg",
      "/download/v0.5.0%2Ftau.dmg",
      "/download/v0.5.0/%2e%2e/tau.dmg",
      "/download/v0.5.0/..%2F..%2Fsecret",
      "/download/%74au.dmg",
    ];
    for (const path of refused) expect(downloadOf(path), path).toBeNull();
  });

  it("take a strict semver version", () => {
    for (const version of ["0.0.0", "0.5.0", "10.20.30", "1.0.0-0a.is.legal", "1.0.0-rc.1"]) {
      expect(SEMVER.test(version), version).toBe(true);
    }
    const bad = ["1", "1.2", "1.2.3.4", "01.2.3", "1.2.3-", "1.2.3-01", "1.2.3+x", "v1.2.3"];
    for (const version of bad) expect(SEMVER.test(version), version).toBe(false);
  });

  it("never reach the bucket for a path outside the allowlist", async () => {
    const bucket = bucketWithRelease();
    const env = envWith(bucket);
    for (const path of [
      "/download",
      "/download/index.html",
      "/download/v0.5.0/latest.json",
      "/download/v0.5.0/..%2F..%2Flatest.json",
      "/download/..%2f..%2fwrangler.jsonc",
      "/download/v9/tau.dmg",
      "/",
      "/api/universe",
    ]) {
      expect(await fetchDownload(env, path), path).toBeNull();
      expect(await fetchDownload(env, path, { method: "POST" }), path).toBeNull();
    }
    expect(bucket.calls).toEqual([]);
  });

  it("resolve dot segments before matching, like every URL", async () => {
    const bucket = bucketWithRelease();
    const env = envWith(bucket);
    // The URL parser removes `..` (also %2e%2e): what is left is matched as it is.
    expect(await fetchDownload(env, "/download/v0.5.0/../../tau.dmg")).toBeNull();
    expect(await fetchDownload(env, "/download/v0.5.0/%2e%2e/%2e%2e/etc/passwd")).toBeNull();
    const res = await download(env, "/download/v0.5.0/../latest.json");
    expect(res.status).toBe(200);
    expect(bucket.calls).toEqual(["head latest.json", "get latest.json"]);
  });

  it("do not collide with the page routes", () => {
    expect(isReservedName("download")).toBe(true);
    for (const path of [
      "/download/",
      "/download/tau.dmg",
      "/download/latest.json",
      "/download/tau.app.tar.gz",
      "/download/v0.5.0/tau.dmg",
      "/download/v0.5.0/tau.app.tar.gz",
    ]) {
      expect(pageRoute(path), path).toBeNull();
      expect(isForwarded(path), path).toBe(false);
    }
  });

  it("redirect /download/ to the download page", async () => {
    const env = envWith(bucketWithRelease());
    const res = await download(env, "/download/?lang=tr");
    expect(res.status).toBe(301);
    expect(res.headers.get("location")).toBe("/download?lang=tr");
  });
});

describe("serving a download", () => {
  it("serves the disk image as an attachment, cached briefly", async () => {
    const bucket = bucketWithRelease();
    const res = await download(envWith(bucket), "/download/tau.dmg");
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toBe("application/x-apple-diskimage");
    expect(res.headers.get("content-disposition")).toBe('attachment; filename="tau.dmg"');
    expect(res.headers.get("cache-control")).toBe(LATEST_CACHE);
    expect(LATEST_CACHE).toBe("public, max-age=300");
    expect(res.headers.get("etag")).toBe('"dmg-latest"');
    expect(res.headers.get("last-modified")).toBe(UPLOADED.toUTCString());
    expect(res.headers.get("accept-ranges")).toBe("bytes");
    expect(res.headers.get("content-length")).toBe(String(DMG.length));
    expect(await bytesOf(res)).toBe(DMG);
    expect(bucket.calls).toEqual(["head tau.dmg", "get tau.dmg"]);
  });

  it("serves the updater's manifest and archive", async () => {
    const env = envWith(bucketWithRelease());
    const manifest = await download(env, "/download/latest.json");
    expect(manifest.status).toBe(200);
    expect(manifest.headers.get("content-type")).toBe("application/json");
    expect(manifest.headers.get("content-disposition")).toBeNull();
    expect(manifest.headers.get("cache-control")).toBe(LATEST_CACHE);
    expect(await manifest.json()).toEqual(JSON.parse(MANIFEST));

    const archive = await download(env, "/download/tau.app.tar.gz");
    expect(archive.status).toBe(200);
    expect(archive.headers.get("content-type")).toBe("application/gzip");
    expect(archive.headers.get("cache-control")).toBe(LATEST_CACHE);
    expect(await bytesOf(archive)).toBe(ARCHIVE);
  });

  it("caches a release's own files for good", async () => {
    const env = envWith(bucketWithRelease());
    const dmg = await download(env, "/download/v0.5.0/tau.dmg");
    expect(dmg.status).toBe(200);
    expect(dmg.headers.get("cache-control")).toBe(VERSIONED_CACHE);
    expect(VERSIONED_CACHE).toBe("public, max-age=31536000, immutable");
    expect(dmg.headers.get("content-disposition")).toBe('attachment; filename="tau.dmg"');
    expect(dmg.headers.get("etag")).toBe('"dmg-v050"');
    expect(await bytesOf(dmg)).toBe(DMG);

    const archive = await download(env, "/download/v0.5.0/tau.app.tar.gz");
    expect(archive.status).toBe(200);
    expect(archive.headers.get("content-type")).toBe("application/gzip");
    expect(archive.headers.get("cache-control")).toBe(VERSIONED_CACHE);
    expect(await bytesOf(archive)).toBe(ARCHIVE);
  });

  it("answers HEAD with the headers only, reading no body", async () => {
    const bucket = bucketWithRelease();
    const res = await download(envWith(bucket), "/download/tau.dmg", {
      method: "HEAD",
      headers: { range: "bytes=0-3" },
    });
    expect(res.status).toBe(200);
    expect(res.body).toBeNull();
    expect(res.headers.get("content-length")).toBe(String(DMG.length));
    expect(res.headers.get("content-type")).toBe("application/x-apple-diskimage");
    expect(res.headers.get("etag")).toBe('"dmg-latest"');
    expect(res.headers.get("content-range")).toBeNull();
    expect(bucket.calls).toEqual(["head tau.dmg"]);
  });

  it("refuses other methods", async () => {
    const bucket = bucketWithRelease();
    for (const method of ["POST", "PUT", "DELETE"]) {
      const res = await download(envWith(bucket), "/download/latest.json", { method });
      expect(res.status, method).toBe(405);
      expect(res.headers.get("allow")).toBe("GET, HEAD");
    }
    expect(bucket.calls).toEqual([]);
  });

  it("answers 404 for a file the bucket does not have", async () => {
    const bucket = new FakeBucket();
    for (const path of ["/download/latest.json", "/download/v0.6.0/tau.dmg"]) {
      for (const method of ["GET", "HEAD"]) {
        const res = await download(envWith(bucket), path, { method });
        expect(res.status, `${method} ${path}`).toBe(404);
        expect(res.headers.get("cache-control")).toBe("no-store");
        if (method === "GET") expect(await res.json()).toEqual({ error: "not_found" });
      }
    }
  });

  it("answers 503 without the bucket binding", async () => {
    for (const method of ["GET", "HEAD"]) {
      const res = await download({}, "/download/tau.dmg", { method });
      expect(res.status, method).toBe(503);
      expect(res.headers.get("cache-control")).toBe("no-store");
      if (method === "GET") expect(await res.json()).toEqual({ error: "downloads_unavailable" });
    }
  });

  it("reads the new file when a release replaces it between the two reads", async () => {
    const bucket = bucketWithRelease();
    bucket.afterHead = () => bucket.put("latest.json", '{"version":"0.6.0"}', "json-0.6.0");
    const res = await download(envWith(bucket), "/download/latest.json");
    expect(res.status).toBe(200);
    expect(res.headers.get("etag")).toBe('"json-0.6.0"');
    expect(await res.json()).toEqual({ version: "0.6.0" });
    expect(bucket.calls).toEqual([
      "head latest.json",
      "get latest.json",
      "head latest.json",
      "get latest.json",
    ]);
  });
});

describe("conditional requests", () => {
  it("answers 304 to a matching If-None-Match", async () => {
    const bucket = bucketWithRelease();
    const env = envWith(bucket);
    for (const value of [
      '"dmg-latest"',
      'W/"dmg-latest"',
      '"other", "dmg-latest"',
      "*",
    ]) {
      for (const method of ["GET", "HEAD"]) {
        const res = await download(env, "/download/tau.dmg", {
          method,
          headers: { "if-none-match": value },
        });
        expect(res.status, `${method} ${value}`).toBe(304);
        expect(res.body).toBeNull();
        expect(res.headers.get("etag")).toBe('"dmg-latest"');
        expect(res.headers.get("cache-control")).toBe(LATEST_CACHE);
        expect(res.headers.get("last-modified")).toBe(UPLOADED.toUTCString());
      }
    }
    // Revalidation reads metadata only.
    expect(bucket.calls.every((call) => call === "head tau.dmg")).toBe(true);
  });

  it("serves the file to a stale If-None-Match", async () => {
    const res = await download(envWith(bucketWithRelease()), "/download/tau.dmg", {
      headers: { "if-none-match": '"dmg-v040"' },
    });
    expect(res.status).toBe(200);
    expect(await bytesOf(res)).toBe(DMG);
  });

  it("uses If-Modified-Since only without If-None-Match", async () => {
    const env = envWith(bucketWithRelease());
    const later = new Date(UPLOADED.getTime() + 60_000).toUTCString();
    const earlier = new Date(UPLOADED.getTime() - 60_000).toUTCString();
    const same = await download(env, "/download/latest.json", {
      headers: { "if-modified-since": UPLOADED.toUTCString() },
    });
    expect(same.status).toBe(304);
    const after = await download(env, "/download/latest.json", {
      headers: { "if-modified-since": later },
    });
    expect(after.status).toBe(304);
    const before = await download(env, "/download/latest.json", {
      headers: { "if-modified-since": earlier },
    });
    expect(before.status).toBe(200);
    await before.body?.cancel();
    const tagWins = await download(env, "/download/latest.json", {
      headers: { "if-none-match": '"old"', "if-modified-since": later },
    });
    expect(tagWins.status).toBe(200);
    await tagWins.body?.cancel();
  });
});

describe("byte ranges", () => {
  it("serves one range as 206 with Content-Range", async () => {
    const bucket = bucketWithRelease();
    const env = envWith(bucket);
    const cases: [string, string, string][] = [
      ["bytes=0-3", "bytes 0-3/20", DMG.slice(0, 4)],
      ["bytes=16-", "bytes 16-19/20", DMG.slice(16)],
      ["bytes=-5", "bytes 15-19/20", DMG.slice(15)],
      ["bytes=10-99", "bytes 10-19/20", DMG.slice(10)],
      ["bytes=-50", "bytes 0-19/20", DMG],
      ["BYTES=2-2", "bytes 2-2/20", DMG.slice(2, 3)],
    ];
    for (const [range, contentRange, body] of cases) {
      const res = await download(env, "/download/v0.5.0/tau.dmg", { headers: { range } });
      expect(res.status, range).toBe(206);
      expect(res.headers.get("content-range"), range).toBe(contentRange);
      expect(res.headers.get("content-length"), range).toBe(String(body.length));
      expect(res.headers.get("content-type")).toBe("application/x-apple-diskimage");
      expect(res.headers.get("etag")).toBe('"dmg-v050"');
      expect(await bytesOf(res), range).toBe(body);
    }
    expect(bucket.calls).toContain("get v0.5.0/tau.dmg 0+4");
  });

  it("answers 416 to a range past the end", async () => {
    const env = envWith(bucketWithRelease());
    for (const range of ["bytes=20-", "bytes=99-100", "bytes=-0"]) {
      const res = await download(env, "/download/tau.dmg", { headers: { range } });
      expect(res.status, range).toBe(416);
      expect(res.headers.get("content-range"), range).toBe("bytes */20");
      expect(res.body).toBeNull();
    }
  });

  it("serves the whole file for ranges it does not take", async () => {
    const env = envWith(bucketWithRelease());
    for (const range of ["bytes=0-1,4-5", "bytes=5-2", "bytes=-", "items=0-1", "bytes=a-b", ""]) {
      const res = await download(env, "/download/tau.dmg", { headers: { range } });
      expect(res.status, range).toBe(200);
      expect(res.headers.get("content-range")).toBeNull();
      expect(await bytesOf(res)).toBe(DMG);
    }
  });

  it("honours If-Range: a range of an older file becomes the whole new file", async () => {
    const env = envWith(bucketWithRelease());
    const current = await download(env, "/download/tau.dmg", {
      headers: { range: "bytes=0-3", "if-range": '"dmg-latest"' },
    });
    expect(current.status).toBe(206);
    expect(await bytesOf(current)).toBe(DMG.slice(0, 4));

    const byDate = await download(env, "/download/tau.dmg", {
      headers: { range: "bytes=0-3", "if-range": UPLOADED.toUTCString() },
    });
    expect(byDate.status).toBe(206);
    await byDate.body?.cancel();

    for (const ifRange of ['"dmg-v040"', 'W/"dmg-latest"', "Thu, 01 Jan 2026 00:00:00 GMT"]) {
      const res = await download(env, "/download/tau.dmg", {
        headers: { range: "bytes=0-3", "if-range": ifRange },
      });
      expect(res.status, ifRange).toBe(200);
      expect(await bytesOf(res)).toBe(DMG);
    }
  });

  it("parses single ranges strictly", () => {
    expect(byteRange(null, 10)).toBeNull();
    expect(byteRange("bytes=0-0", 10)).toEqual({ offset: 0, length: 1 });
    expect(byteRange(" bytes=3-5 ", 10)).toEqual({ offset: 3, length: 3 });
    expect(byteRange("bytes=0-", 0)).toBe("unsatisfiable");
    expect(byteRange("bytes=-1", 0)).toBe("unsatisfiable");
    expect(byteRange("bytes=1234567890123456-", 10)).toBeNull();
  });
});
