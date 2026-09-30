/**
 * The errors of envelopes, as in tau-net: every failure to build, verify or open an envelope
 * is an EnvelopeError whose `reason` is a short fixed English phrase for logs (never a key,
 * never plaintext).
 */

export class EnvelopeError extends Error {
  override name = "EnvelopeError";
  readonly reason: string;

  constructor(reason: string) {
    super(reason);
    this.reason = reason;
  }
}

/** Not an envelope of protocol v1: wrong shape, types or values. */
export class MalformedEnvelope extends EnvelopeError {
  override name = "MalformedEnvelope";
}

/** The signature does not verify with the key it was checked against. */
export class BadSignature extends EnvelopeError {
  override name = "BadSignature";
}

/** The box cannot be sealed, does not open with this identity and header, or its content is malformed. */
export class BoxError extends EnvelopeError {
  override name = "BoxError";
}

/** The envelope would exceed MAX_ENVELOPE_BYTES. */
export class EnvelopeTooLarge extends EnvelopeError {
  override name = "EnvelopeTooLarge";
}
