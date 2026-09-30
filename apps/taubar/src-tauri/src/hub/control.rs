//! Signed requests to the hub's protected control routes (ADR 0008 decision 8).
//!
//! The Rust twin of tau-core's `tau_core.hub.control` (`request_auth`, `response_proof`,
//! `read_token`) and `tau_core.hub.client.HubClient`, byte for byte:
//!
//! - The control token in `hub_dir/control.token` never travels. It is read from the file on
//!   every request (a restarted hub writes a new one; it is never cached) and read once more
//!   after a 403.
//! - A request carries a fresh `X-Tau-Nonce` and
//!   `X-Tau-Auth = hex(HMAC-SHA256(token, "req" | nonce | METHOD | path))`, with
//!   `Content-Type: application/json` and no `Origin`; the path has no query string.
//! - The answer must carry `X-Tau-Proof = hex(HMAC-SHA256(token, "resp" | nonce | METHOD | path
//!   | status | body))` over the exact body bytes. A missing or wrong proof, a redirect (never
//!   followed), no token file, nothing listening, a timeout or a body that is not JSON all mean
//!   "no trustworthy hub" ([`ControlError::Unavailable`]): a process that bound the port while
//!   the hub was down cannot sign with a token it never saw.
//!
//! The `|` joins are pinned in tau-core's `test_request_auth_and_proof_are_separate_hmac_domains`
//! and in this module's tests with the same vectors.

use super::probe::{self, HttpResponse};
use hmac::{Hmac, Mac};
use serde_json::Value;
use sha2::Sha256;
use std::fmt;
use std::path::{Path, PathBuf};
use std::time::Duration;

/// The control token's file name in `hub_dir` (0600, written by the hub on start).
pub const TOKEN_FILE: &str = "control.token";
pub const NONCE_HEADER: &str = "X-Tau-Nonce";
pub const AUTH_HEADER: &str = "X-Tau-Auth";
pub const PROOF_HEADER: &str = "X-Tau-Proof";

type HmacSha256 = Hmac<Sha256>;

fn mac(token: &str, domain: &[u8], fields: &[&str], tail: Option<&[u8]>) -> HmacSha256 {
    let mut mac =
        HmacSha256::new_from_slice(token.as_bytes()).expect("HMAC takes a key of any length");
    mac.update(domain);
    for field in fields {
        mac.update(b"|");
        mac.update(field.as_bytes());
    }
    if let Some(tail) = tail {
        mac.update(b"|");
        mac.update(tail);
    }
    mac
}

/// `hex(HMAC-SHA256(token, "req" | nonce | METHOD | path))`: the `X-Tau-Auth` of a request.
pub fn request_auth(token: &str, nonce: &str, method: &str, path: &str) -> String {
    let method = method.to_ascii_uppercase();
    hex::encode(
        mac(token, b"req", &[nonce, &method, path], None)
            .finalize()
            .into_bytes(),
    )
}

fn proof_mac(
    token: &str,
    nonce: &str,
    method: &str,
    path: &str,
    status: u16,
    body: &[u8],
) -> HmacSha256 {
    let method = method.to_ascii_uppercase();
    let status = status.to_string();
    mac(token, b"resp", &[nonce, &method, path, &status], Some(body))
}

/// `hex(HMAC-SHA256(token, "resp" | nonce | METHOD | path | status | body))`: the
/// `X-Tau-Proof` of an answer. The `resp` domain keeps a request's auth value from ever
/// passing as a proof.
pub fn response_proof(
    token: &str,
    nonce: &str,
    method: &str,
    path: &str,
    status: u16,
    body: &[u8],
) -> String {
    hex::encode(
        proof_mac(token, nonce, method, path, status, body)
            .finalize()
            .into_bytes(),
    )
}

/// Does `given` (the answer's `X-Tau-Proof`) prove this answer? Compared in constant time.
///
/// Only the 64 lower-case hex digits `hexdigest()` writes count: tau-core compares the hex
/// strings, so the same MAC in upper case is no proof there, and none here either.
pub fn proof_matches(
    token: &str,
    nonce: &str,
    method: &str,
    path: &str,
    status: u16,
    body: &[u8],
    given: &str,
) -> bool {
    let lower_hex = given.len() == 64
        && given
            .bytes()
            .all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'));
    if !lower_hex {
        return false;
    }
    let Ok(bytes) = hex::decode(given) else {
        return false;
    };
    proof_mac(token, nonce, method, path, status, body)
        .verify_slice(&bytes)
        .is_ok()
}

/// The token in `path`: `None` when the file is missing, unreadable, not UTF-8 or empty.
pub fn read_token(path: &Path) -> Option<String> {
    let text = std::fs::read_to_string(path).ok()?;
    let token = text.trim();
    (!token.is_empty()).then(|| token.to_string())
}

/// `n` random bytes as lower-case hex (`secrets.token_hex(n)`).
pub fn random_hex(n: usize) -> Result<String, String> {
    let mut bytes = vec![0u8; n];
    getrandom::fill(&mut bytes).map_err(|e| format!("no randomness for a nonce: {e}"))?;
    Ok(hex::encode(bytes))
}

/// Why a protected call gave no trustworthy answer.
#[derive(Clone, Debug, PartialEq)]
pub enum ControlError {
    /// No trustworthy hub answered: nothing listens, no token file, a timeout, a redirect, a
    /// missing or wrong proof, or a body that is not JSON (`HubUnavailable` in tau-core).
    Unavailable(String),
    /// The hub answered with a non-2xx status: a proven answer (with its payload), or a 403
    /// that stayed a 403 after the token was read again (never signed, so no payload).
    Refused { status: u16, payload: Option<Value> },
}

impl fmt::Display for ControlError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Unavailable(why) => write!(f, "no trustworthy hub answered: {why}"),
            Self::Refused { status: 403, .. } => write!(
                f,
                "the hub refused the signed request (403), also after reading the token again"
            ),
            Self::Refused { status, payload } => {
                let error = payload
                    .as_ref()
                    .and_then(|p| p.get("error").or_else(|| p.get("reason")))
                    .and_then(Value::as_str);
                match error {
                    Some(error) => write!(f, "the hub answered {status}: {error}"),
                    None => write!(f, "the hub answered {status}"),
                }
            }
        }
    }
}

/// A caller of the hub's protected control routes on `127.0.0.1:<port>`. Blocking; run it off
/// the main thread.
#[derive(Clone, Debug)]
pub struct ControlClient {
    pub port: u16,
    pub token_path: PathBuf,
    pub timeout: Duration,
}

impl ControlClient {
    pub fn new(port: u16, hub_dir: &Path, timeout: Duration) -> Self {
        Self {
            port,
            token_path: hub_dir.join(TOKEN_FILE),
            timeout,
        }
    }

    /// `POST path` with `body` as JSON → the JSON payload of a proven 2xx answer (`null` for
    /// an empty body).
    pub fn post(&self, path: &str, body: &Value) -> Result<Value, ControlError> {
        let data = serde_json::to_vec(body)
            .map_err(|e| ControlError::Unavailable(format!("the request is not JSON: {e}")))?;
        let method = "POST";
        let mut answer: Option<(String, String, HttpResponse)> = None;
        for attempt in 0..2 {
            let token = read_token(&self.token_path).ok_or_else(|| {
                ControlError::Unavailable(format!(
                    "no control token in {}",
                    self.token_path.display()
                ))
            })?;
            let nonce = random_hex(16).map_err(ControlError::Unavailable)?;
            let auth = request_auth(&token, &nonce, method, path);
            let response = probe::http_post(
                self.port,
                path,
                &[(NONCE_HEADER, &nonce), (AUTH_HEADER, &auth)],
                &data,
                self.timeout,
            )
            .map_err(|e| {
                ControlError::Unavailable(format!("no hub answers on port {}: {e}", self.port))
            })?;
            let retry = response.status == 403 && attempt == 0;
            answer = Some((token, nonce, response));
            if !retry {
                break; // a 403 on the first try: the hub may have restarted; re-read the token
            }
        }
        let (token, nonce, response) = answer.expect("at least one attempt");
        let status = response.status;
        if (300..400).contains(&status) {
            return Err(ControlError::Unavailable(format!(
                "the answer to {method} {path} is a redirect"
            )));
        }
        if status == 403 {
            // Refused before dispatch, so unsigned: its body is never read.
            return Err(ControlError::Refused {
                status,
                payload: None,
            });
        }
        let payload = parse_body(&response.body);
        let proven = response.header(PROOF_HEADER).is_some_and(|given| {
            proof_matches(&token, &nonce, method, path, status, &response.body, given)
        });
        if !proven {
            return Err(ControlError::Unavailable(format!(
                "the answer to {method} {path} has no valid proof"
            )));
        }
        let payload = payload.map_err(|()| {
            ControlError::Unavailable(format!("the answer to {method} {path} is not JSON"))
        })?;
        if !(200..300).contains(&status) {
            return Err(ControlError::Refused {
                status,
                payload: Some(payload),
            });
        }
        Ok(payload)
    }
}

fn parse_body(body: &[u8]) -> Result<Value, ()> {
    if body.is_empty() {
        return Ok(Value::Null);
    }
    serde_json::from_slice(body).map_err(|_| ())
}

#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use serde_json::json;
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::{Arc, Mutex};

    /// The bytes tau-core pins in `test_request_auth_and_proof_are_separate_hmac_domains`,
    /// computed there with Python's `hmac` (key `tok`).
    #[test]
    fn signing_matches_tau_core_byte_for_byte() {
        // hmac.new(b"tok", b"req|n|GET|/guard/status", sha256).hexdigest()
        assert_eq!(
            request_auth("tok", "n", "get", "/guard/status"),
            "24e51f7b3a8dd4837a48357f2f5fe6ec87a2260ef24a34840c40368a49115355"
        );
        // hmac.new(b"tok", b"resp|n|GET|/guard/status|200|{}", sha256).hexdigest()
        assert_eq!(
            response_proof("tok", "n", "GET", "/guard/status", 200, b"{}"),
            "c130bbc7fd3844c190f210f5e216cb06b3f5562aeea2c74745656377d1b4f4ff"
        );
        // tau_core.hub.control.request_auth("tok", "n-123", "POST", "/guard/lock")
        assert_eq!(
            request_auth("tok", "n-123", "POST", "/guard/lock"),
            "a3d55845b79f62a24688686f1a1d7603e0b1774e256babbb4a325dc839e0409a"
        );
        // response_proof("tok", "n-123", "POST", "/guard/lock", 200, b'{"state": "locked"}')
        assert_eq!(
            response_proof(
                "tok",
                "n-123",
                "POST",
                "/guard/lock",
                200,
                br#"{"state": "locked"}"#
            ),
            "01f066d0a9084731ac8d1e9144471cd6a60d27e9eb16bcf7febe5ba15f04c5fe"
        );
        // Non-ASCII key and nonce are UTF-8, as in Python's str.encode("utf-8").
        assert_eq!(
            request_auth("t\u{f6}k", "n\u{e9}", "POST", "/guard/lock"),
            "24972de2712d1ce5a3f04c94614884b1cf24ebfa04228a0e2a933cd4c7f8997e"
        );
    }

    #[test]
    fn auth_and_proof_are_separate_domains() {
        let auth = request_auth("tok", "n", "GET", "/guard/status");
        assert_ne!(
            auth,
            response_proof("tok", "n", "GET", "/guard/status", 200, b"")
        );
        let proof = response_proof("tok", "n", "POST", "/guard/lock", 200, b"{}");
        assert!(proof_matches(
            "tok",
            "n",
            "POST",
            "/guard/lock",
            200,
            b"{}",
            &proof
        ));
        assert!(!proof_matches(
            "tok",
            "n",
            "POST",
            "/guard/lock",
            200,
            b"{} ",
            &proof
        ));
        assert!(!proof_matches(
            "tok",
            "m",
            "POST",
            "/guard/lock",
            200,
            b"{}",
            &proof
        ));
        assert!(!proof_matches(
            "tok",
            "n",
            "POST",
            "/guard/lock",
            201,
            b"{}",
            &proof
        ));
        assert!(!proof_matches(
            "other",
            "n",
            "POST",
            "/guard/lock",
            200,
            b"{}",
            &proof
        ));
        assert!(!proof_matches(
            "tok",
            "n",
            "POST",
            "/guard/lock",
            200,
            b"{}",
            "not hex"
        ));
        assert!(!proof_matches(
            "tok",
            "n",
            "POST",
            "/guard/lock",
            200,
            b"{}",
            &proof[..62]
        ));
        // The same MAC in upper case or with padding is no proof, as in tau-core's
        // compare_digest on the lower-case hex string.
        assert!(proof.bytes().any(|b| b.is_ascii_alphabetic()));
        for variant in [
            proof.to_ascii_uppercase(),
            format!(" {proof}"),
            format!("{proof}00"),
        ] {
            assert!(
                !proof_matches("tok", "n", "POST", "/guard/lock", 200, b"{}", &variant),
                "{variant}"
            );
        }
    }

    #[test]
    fn nonces_are_fresh_and_tokens_are_read_trimmed() {
        let a = random_hex(16).unwrap();
        assert_eq!(a.len(), 32);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
        assert_ne!(a, random_hex(16).unwrap());
        let dir = tmpdir("token");
        let path = dir.join(TOKEN_FILE);
        assert_eq!(read_token(&path), None);
        std::fs::write(&path, "  \n").unwrap();
        assert_eq!(read_token(&path), None);
        std::fs::write(&path, "abc-DEF_123\n").unwrap();
        assert_eq!(read_token(&path).as_deref(), Some("abc-DEF_123"));
    }

    pub(crate) fn tmpdir(name: &str) -> PathBuf {
        let dir =
            std::env::temp_dir().join(format!("taubar-control-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    /// One request as the fake hub received it.
    #[derive(Clone, Debug)]
    pub(crate) struct Seen {
        pub raw: Vec<u8>,
        pub method: String,
        pub path: String,
        pub headers: Vec<(String, String)>,
        pub body: Vec<u8>,
    }

    impl Seen {
        pub fn header(&self, name: &str) -> Option<&str> {
            self.headers
                .iter()
                .find(|(k, _)| k.eq_ignore_ascii_case(name))
                .map(|(_, v)| v.as_str())
        }
    }

    /// What the fake hub sends back: status, extra headers, body.
    pub(crate) type Reply = (u16, Vec<(String, String)>, Vec<u8>);

    /// A loopback server that answers `answers` connections with a closure, then stops.
    pub(crate) struct FakeHub {
        pub port: u16,
        pub seen: Arc<Mutex<Vec<Seen>>>,
        thread: Option<std::thread::JoinHandle<()>>,
    }

    impl FakeHub {
        pub fn start<F>(answers: usize, reply: F) -> Self
        where
            F: Fn(usize, &Seen) -> Reply + Send + 'static,
        {
            let listener = TcpListener::bind("127.0.0.1:0").unwrap();
            let port = listener.local_addr().unwrap().port();
            let seen = Arc::new(Mutex::new(Vec::new()));
            let log = seen.clone();
            let thread = std::thread::spawn(move || {
                for index in 0..answers {
                    let Ok((mut conn, _)) = listener.accept() else {
                        return;
                    };
                    let request = read_request(&mut conn);
                    let (status, headers, body) = reply(index, &request);
                    log.lock().unwrap().push(request);
                    let mut head = format!("HTTP/1.0 {status} X\r\n");
                    for (name, value) in headers {
                        head.push_str(&format!("{name}: {value}\r\n"));
                    }
                    head.push_str(&format!("Content-Length: {}\r\n\r\n", body.len()));
                    let _ = conn.write_all(head.as_bytes());
                    let _ = conn.write_all(&body);
                }
            });
            Self {
                port,
                seen,
                thread: Some(thread),
            }
        }

        pub fn requests(&mut self) -> Vec<Seen> {
            if let Some(thread) = self.thread.take() {
                let _ = thread.join();
            }
            self.seen.lock().unwrap().clone()
        }
    }

    fn read_request(conn: &mut std::net::TcpStream) -> Seen {
        conn.set_read_timeout(Some(Duration::from_secs(5))).ok();
        let mut raw = Vec::new();
        let mut buf = [0u8; 1024];
        let head_end = loop {
            if let Some(pos) = raw.windows(4).position(|w| w == b"\r\n\r\n") {
                break pos;
            }
            let n = conn.read(&mut buf).unwrap_or(0);
            if n == 0 {
                break raw.len();
            }
            raw.extend_from_slice(&buf[..n]);
        };
        let head = String::from_utf8_lossy(&raw[..head_end]).to_string();
        let mut lines = head.split("\r\n");
        let first: Vec<&str> = lines.next().unwrap_or("").split(' ').collect();
        let headers: Vec<(String, String)> = lines
            .filter_map(|l| l.split_once(':'))
            .map(|(k, v)| (k.trim().to_string(), v.trim().to_string()))
            .collect();
        let length: usize = headers
            .iter()
            .find(|(k, _)| k.eq_ignore_ascii_case("content-length"))
            .and_then(|(_, v)| v.parse().ok())
            .unwrap_or(0);
        let start = (head_end + 4).min(raw.len());
        while raw.len() < start + length {
            let n = conn.read(&mut buf).unwrap_or(0);
            if n == 0 {
                break;
            }
            raw.extend_from_slice(&buf[..n]);
        }
        Seen {
            method: first.first().unwrap_or(&"").to_string(),
            path: first.get(1).unwrap_or(&"").to_string(),
            headers,
            body: raw[start..(start + length).min(raw.len())].to_vec(),
            raw,
        }
    }

    /// A reply signed the way the hub signs: with `token`, over this request's nonce.
    pub(crate) fn signed(token: &str, seen: &Seen, status: u16, body: &[u8]) -> Reply {
        let nonce = seen.header(NONCE_HEADER).unwrap_or("");
        let proof = response_proof(token, nonce, &seen.method, &seen.path, status, body);
        (
            status,
            vec![
                (
                    "Content-Type".into(),
                    "application/json; charset=utf-8".into(),
                ),
                (PROOF_HEADER.into(), proof),
            ],
            body.to_vec(),
        )
    }

    /// Does the request carry a valid `X-Tau-Auth` for `token`?
    pub(crate) fn authorized(token: &str, seen: &Seen) -> bool {
        match (seen.header(NONCE_HEADER), seen.header(AUTH_HEADER)) {
            (Some(nonce), Some(auth)) => {
                auth == request_auth(token, nonce, &seen.method, &seen.path)
            }
            _ => false,
        }
    }

    fn forbidden() -> Reply {
        (403, vec![], br#"{"error": "forbidden"}"#.to_vec())
    }

    fn client(hub: &FakeHub, dir: &Path) -> ControlClient {
        ControlClient::new(hub.port, dir, Duration::from_secs(3))
    }

    #[test]
    fn a_signed_post_reaches_a_hub_that_checks_it_like_tau_core() {
        let dir = tmpdir("happy");
        std::fs::write(dir.join(TOKEN_FILE), "secret-token-1\n").unwrap();
        let mut hub = FakeHub::start(1, |_, seen| {
            let ok = authorized("secret-token-1", seen)
                && seen.header("Origin").is_none()
                && seen.header("Content-Type") == Some("application/json");
            if ok {
                signed("secret-token-1", seen, 200, br#"{"ok": true}"#)
            } else {
                forbidden()
            }
        });
        let answer = client(&hub, &dir).post("/echo", &json!({"a": 1})).unwrap();
        assert_eq!(answer, json!({"ok": true}));
        let seen = hub.requests();
        assert_eq!(seen.len(), 1);
        assert_eq!(seen[0].method, "POST");
        assert_eq!(seen[0].path, "/echo");
        assert_eq!(seen[0].header(NONCE_HEADER).map(str::len), Some(32));
        assert_eq!(
            serde_json::from_slice::<Value>(&seen[0].body).unwrap(),
            json!({"a": 1})
        );
        let raw = String::from_utf8_lossy(&seen[0].raw);
        assert!(!raw.contains("secret-token-1"), "the token never travels");
    }

    #[test]
    fn a_403_reads_the_token_again_and_retries_once() {
        let dir = tmpdir("retry");
        let token_file = dir.join(TOKEN_FILE);
        std::fs::write(&token_file, "old-token").unwrap();
        let file = token_file.clone();
        let mut hub = FakeHub::start(2, move |index, seen| {
            if index == 0 {
                // The hub restarted and wrote a new token; the old signature fails.
                assert!(authorized("old-token", seen));
                std::fs::write(&file, "new-token").unwrap();
                forbidden()
            } else if authorized("new-token", seen) {
                signed("new-token", seen, 200, br#"{"state": "locked"}"#)
            } else {
                forbidden()
            }
        });
        let answer = client(&hub, &dir).post("/guard/lock", &json!({})).unwrap();
        assert_eq!(answer, json!({"state": "locked"}));
        let seen = hub.requests();
        assert_eq!(seen.len(), 2);
        assert_ne!(seen[0].header(NONCE_HEADER), seen[1].header(NONCE_HEADER));
    }

    #[test]
    fn a_second_403_is_refused_without_a_third_try() {
        let dir = tmpdir("forbidden");
        std::fs::write(dir.join(TOKEN_FILE), "tok").unwrap();
        let mut hub = FakeHub::start(3, |_, _| forbidden());
        let err = client(&hub, &dir)
            .post("/guard/lock", &json!({}))
            .unwrap_err();
        assert!(
            matches!(err, ControlError::Refused { status: 403, .. }),
            "{err:?}"
        );
        assert!(err.to_string().contains("403"));
        drop(std::net::TcpStream::connect(("127.0.0.1", hub.port))); // release the third accept
        let posts = hub
            .requests()
            .iter()
            .filter(|seen| seen.method == "POST")
            .count();
        assert_eq!(posts, 2, "one try, one retry after re-reading the token");
    }

    #[test]
    fn a_missing_or_wrong_proof_means_no_trustworthy_hub() {
        let dir = tmpdir("proof");
        std::fs::write(dir.join(TOKEN_FILE), "tok").unwrap();
        // A squatter that knows the protocol but not the token.
        type Case = Box<dyn Fn(&Seen) -> Reply + Send>;
        let cases: Vec<Case> = vec![
            Box::new(|_| (200, vec![], br#"{"state": "locked"}"#.to_vec())),
            Box::new(|seen| signed("guessed", seen, 200, br#"{"state": "locked"}"#)),
            Box::new(|seen| {
                // Signed for another body than the one sent.
                let (status, headers, _) = signed("tok", seen, 200, br#"{"state": "locked"}"#);
                (status, headers, br#"{"state": "unlocked"}"#.to_vec())
            }),
            Box::new(|seen| {
                // The request's own auth value echoed back as a proof.
                let auth = seen.header(AUTH_HEADER).unwrap_or("").to_string();
                (200, vec![(PROOF_HEADER.into(), auth)], b"{}".to_vec())
            }),
        ];
        for case in cases {
            let mut hub = FakeHub::start(1, move |_, seen| case(seen));
            let err = client(&hub, &dir)
                .post("/guard/lock", &json!({}))
                .unwrap_err();
            assert!(matches!(err, ControlError::Unavailable(_)), "{err:?}");
            assert!(err.to_string().contains("proof"), "{err}");
            assert_eq!(hub.requests().len(), 1);
        }
    }

    #[test]
    fn a_redirect_is_never_followed() {
        let dir = tmpdir("redirect");
        std::fs::write(dir.join(TOKEN_FILE), "tok").unwrap();
        let mut hub = FakeHub::start(1, |_, seen| {
            let (_, mut headers, body) = signed("tok", seen, 302, b"{}");
            headers.push(("Location".into(), "http://127.0.0.1:1/elsewhere".into()));
            (302, headers, body)
        });
        let err = client(&hub, &dir)
            .post("/guard/lock", &json!({}))
            .unwrap_err();
        assert!(matches!(err, ControlError::Unavailable(_)), "{err:?}");
        assert!(err.to_string().contains("redirect"), "{err}");
        assert_eq!(hub.requests().len(), 1);
    }

    #[test]
    fn a_proven_error_answer_is_refused_with_its_payload() {
        let dir = tmpdir("error");
        std::fs::write(dir.join(TOKEN_FILE), "tok").unwrap();
        let mut hub = FakeHub::start(1, |_, seen| {
            signed("tok", seen, 404, br#"{"error": "not found"}"#)
        });
        let err = client(&hub, &dir)
            .post("/guard/lock", &json!({}))
            .unwrap_err();
        assert_eq!(
            err,
            ControlError::Refused {
                status: 404,
                payload: Some(json!({"error": "not found"}))
            }
        );
        assert_eq!(err.to_string(), "the hub answered 404: not found");
        hub.requests();
    }

    #[test]
    fn a_proven_body_that_is_not_json_is_unavailable() {
        let dir = tmpdir("notjson");
        std::fs::write(dir.join(TOKEN_FILE), "tok").unwrap();
        let mut hub = FakeHub::start(1, |_, seen| signed("tok", seen, 200, b"<html>"));
        let err = client(&hub, &dir)
            .post("/guard/lock", &json!({}))
            .unwrap_err();
        assert!(err.to_string().contains("not JSON"), "{err}");
        hub.requests();
    }

    #[test]
    fn no_token_file_means_no_request_at_all() {
        let dir = tmpdir("notoken");
        let mut hub = FakeHub::start(1, |_, _| forbidden());
        let err = client(&hub, &dir)
            .post("/guard/lock", &json!({}))
            .unwrap_err();
        assert!(err.to_string().contains("no control token"), "{err}");
        drop(std::net::TcpStream::connect(("127.0.0.1", hub.port))); // release the accept
        let seen = hub.requests();
        assert!(seen.iter().all(|s| s.method.is_empty()), "nothing was sent");
    }

    #[test]
    fn nothing_listening_is_unavailable() {
        let dir = tmpdir("nohub");
        std::fs::write(dir.join(TOKEN_FILE), "tok").unwrap();
        let port = TcpListener::bind("127.0.0.1:0")
            .unwrap()
            .local_addr()
            .unwrap()
            .port();
        let err = ControlClient::new(port, &dir, Duration::from_millis(300))
            .post("/guard/lock", &json!({}))
            .unwrap_err();
        assert!(matches!(err, ControlError::Unavailable(_)), "{err:?}");
    }
}
