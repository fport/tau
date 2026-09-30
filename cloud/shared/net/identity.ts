/**
 * A tau's identity: an Ed25519 signing key and an X25519 box key (§2 of
 * docs/reference/tau-network.md), compatible with tau-net's `identity.json`:
 *
 *     {"v": 1, "sign_seed": "<b64u 32 bytes>", "box_seed": "<b64u 32 bytes>"}
 *
 * and with `TAU_NET_IDENTITY`, the same JSON base64url-encoded. The seeds live in private
 * fields: `JSON.stringify(identity)` is `{}`, and only toIdentityJson() and toEnvValue() give
 * them out, for storage that is sealed (tau-host's vault) or kept secret.
 */

import {
  b64uDecode,
  b64uEncode,
  isObject,
  parseJsonBytes,
  randomBytes,
  utf8Encode,
} from "./b64u.ts";
import { ed25519FromSeed, ed25519Sign, KEY_BYTES, x25519, x25519FromSeed } from "./crypto.ts";

export const SEED_BYTES = KEY_BYTES;

/** The stored form of an identity (tau-net's `identity.json`). */
export interface IdentityJson {
  v: 1;
  sign_seed: string;
  box_seed: string;
}

/** What a hub publishes with `PUT /hub/card`. */
export interface PublicFields {
  name: string;
  sign_key: string;
  box_key: string;
}

/** An identity that cannot be read or is malformed. The message never contains a seed. */
export class IdentityError extends Error {
  override name = "IdentityError";
}

export class Identity {
  readonly #signSeed: Uint8Array;
  readonly #boxSeed: Uint8Array;
  readonly #signingKey: CryptoKey;
  readonly #boxPrivateKey: CryptoKey;
  /** The raw 32-byte public signing key. */
  readonly signKeyBytes: Uint8Array;
  /** The raw 32-byte public box key. */
  readonly boxKeyBytes: Uint8Array;

  private constructor(
    signSeed: Uint8Array,
    boxSeed: Uint8Array,
    signing: { privateKey: CryptoKey; publicKey: Uint8Array },
    box: { privateKey: CryptoKey; publicKey: Uint8Array },
  ) {
    this.#signSeed = signSeed;
    this.#boxSeed = boxSeed;
    this.#signingKey = signing.privateKey;
    this.#boxPrivateKey = box.privateKey;
    this.signKeyBytes = signing.publicKey;
    this.boxKeyBytes = box.publicKey;
  }

  /** The identity of two 32-byte seeds. */
  static async fromSeeds(signSeed: Uint8Array, boxSeed: Uint8Array): Promise<Identity> {
    if (signSeed.length !== SEED_BYTES || boxSeed.length !== SEED_BYTES) {
      throw new IdentityError(`seeds must be ${SEED_BYTES} bytes`);
    }
    const sign = Uint8Array.from(signSeed);
    const box = Uint8Array.from(boxSeed);
    const [signing, boxing] = await Promise.all([ed25519FromSeed(sign), x25519FromSeed(box)]);
    return new Identity(sign, box, signing, boxing);
  }

  /** A fresh identity from the platform's cryptographic random source. */
  static async generate(): Promise<Identity> {
    return Identity.fromSeeds(randomBytes(SEED_BYTES), randomBytes(SEED_BYTES));
  }

  /** From `{"v": 1, "sign_seed", "box_seed"}`; IdentityError otherwise. */
  static async fromJson(data: unknown, source = "memory"): Promise<Identity> {
    if (!isObject(data) || data.v !== 1) {
      throw new IdentityError(`identity from ${source} is not a v1 identity`);
    }
    const sign = b64uDecode(data.sign_seed);
    const box = b64uDecode(data.box_seed);
    if (sign === null || box === null) {
      throw new IdentityError(`identity from ${source} has seeds that are not base64url`);
    }
    if (sign.length !== SEED_BYTES || box.length !== SEED_BYTES) {
      throw new IdentityError(`identity from ${source} has seeds that are not 32 bytes`);
    }
    return Identity.fromSeeds(sign, box);
  }

  /** From the `TAU_NET_IDENTITY` form: the identity JSON, base64url-encoded. */
  static async fromEnvValue(value: string): Promise<Identity> {
    const bytes = b64uDecode(value.trim());
    const data = bytes === null ? undefined : parseJsonBytes(bytes);
    if (data === undefined) {
      throw new IdentityError("TAU_NET_IDENTITY is not base64url-encoded identity JSON");
    }
    return Identity.fromJson(data, "env");
  }

  /** The stored form. It holds the private seeds: seal it or keep it secret. */
  toIdentityJson(): IdentityJson {
    return { v: 1, sign_seed: b64uEncode(this.#signSeed), box_seed: b64uEncode(this.#boxSeed) };
  }

  /** The `TAU_NET_IDENTITY` value. It holds the private seeds: keep it secret. */
  toEnvValue(): string {
    return b64uEncode(utf8Encode(JSON.stringify(this.toIdentityJson())));
  }

  /** The public signing key as published on the card (b64u). */
  get signKey(): string {
    return b64uEncode(this.signKeyBytes);
  }

  /** The public box key as published on the card (b64u). */
  get boxKey(): string {
    return b64uEncode(this.boxKeyBytes);
  }

  /** What a tau publishes on its card besides the fields its host adds. */
  publicFields(name: string): PublicFields {
    return { name, sign_key: this.signKey, box_key: this.boxKey };
  }

  /** The Ed25519 signature of `message` (the caller adds the domain prefix). */
  sign(message: Uint8Array): Promise<Uint8Array> {
    return ed25519Sign(this.#signingKey, message);
  }

  /** The X25519 shared secret of this identity's box key and a peer's public key. */
  sharedSecret(peerPublicKey: Uint8Array): Promise<Uint8Array> {
    return x25519(this.#boxPrivateKey, peerPublicKey);
  }
}
