"""A local Better Auth stand-in: an Ed25519 JWKS server and a token minter.

WHY THIS EXISTS
---------------
The paid proof runs have to be launched by a *signed-in* caller, and nothing
about that is a preference. A builder custom tool is per-user by construction:

* `service/builder_api.py::require_owner` answers **401** to an identity-less
  `POST /api/builder/tools/custom` - "sign in first; tools, MCP servers and
  skills belong to somebody" - so `sounding_line_lookup` cannot even be
  created anonymously;
* `builder/runtime.py::_custom_tool_spec` raises `BuilderRuntimeError` -
  "this run has no identity to look it up for" - at bind time, so an anonymous
  run of a document naming a `ut_` id loses every tool frame at once;
* and `POST /api/builder/validate` does **not** warn about either, because
  `builder/tools.py::tool_problems` leaves a `ut_` id alone when there is
  nobody to ask (`identity_checked: false`).

`docs/observability/evidence/proof/builder-toolfail/inject.md` section 7 is the
finding in full. Its two ways out were "run the paid backend with an identity"
or "drop the custom tool". This script is the first one.

`X-Synthetic-User` is *not* an alternative: `service/app.py::synthetic_identity`
honours it only when the app was built `synthetic=True` **and** `AUTH_BASE_URL`
is unset, and a synthetic app swaps in `SyntheticCrewFactories`, so every run on
it is fake. A paid run needs the real engine, which means the real bearer path.

WHAT IT IS
----------
`service/auth.py` verifies a bearer JWT **offline** against
`${AUTH_BASE_URL}/api/auth/jwks`. It never calls the auth server for anything
else - no token endpoint, no introspection, no session lookup. So the entire
surface a local stand-in has to present is one GET returning a JWKS document,
and the entire surface it has to sign is one EdDSA JWT whose claims satisfy
`verify_token`. Both are in this file and nothing else is.

This is the same construction `tests/service/test_auth_jwt.py` uses - a real
Ed25519 key pair, a real JWKS entry via `jwt.algorithms.OKPAlgorithm.to_jwk`,
real signatures - with the transport unstubbed, because here the transport is
the point.

THE EXACT ENVIRONMENT THE PAID BACKEND NEEDS
--------------------------------------------
`create_app` runs three startup assertions before it builds anything, and two of
them are about this. Set all of the following on the `serve` process:

    AUTH_BASE_URL=http://127.0.0.1:8093
        The issuer, the audience AND the JWKS origin - `auth.py` uses this one
        value for all three (`verify_token` passes it as both `issuer=` and
        `audience=`; `JwksCache.url` appends `/api/auth/jwks`). It must match
        this server's `--issuer`, character for character, with no trailing
        slash: `config.py` strips one, so `http://127.0.0.1:8093/` and
        `http://127.0.0.1:8093` are the same value there, but a token minted
        with the slash would carry it in `iss` and fail the comparison.

        Setting it also turns authentication ON by itself:
        `VALIDATOR_REQUIRE_AUTH` defaults to `bool(AUTH_BASE_URL)`, so the
        half-configured state does not exist. Do not set it separately.

    CREDENTIALS_MASTER_KEY=<base64 of 32 bytes>
        `_assert_credential_vault_startup_safety` raises at startup when
        `AUTH_BASE_URL` is set and this is empty - people can sign in and the
        vault has nowhere to keep their keys. This is remaining-work item 46
        met locally. The placeholder `tests/__init__.py` uses is fine for a
        local backend (it authenticates against nothing):

            Y2ktcGxhY2Vob2xkZXItbm90LWEtbWFzdGVyLWtleSE=

        Mint a real one with:
            python -c "import base64, secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
        and note that CHANGING it later is refused rather than silently
        re-wrapping (`credentials.py`).

    CORS_ALLOW_ORIGINS
        `_assert_auth_startup_safety` refuses `*` while auth is required. It
        does NOT require a value: the default is empty, `"*" in ()` is false,
        and the assertion passes. Leave it unset for a curl-driven proof - a
        browser is not involved, and an empty list fails closed. If a console
        will be pointed at this backend, name the origins instead, e.g.
        `http://localhost:5173,http://127.0.0.1:5173`. Never `*`.

    LANGFUSE_EXPORT_ENABLED=0
        Not an assertion - just keeping an identity check off the trace budget.

    PORT=8094, HOST unset (127.0.0.1), SYNTHETIC unset
        `SYNTHETIC=1` would make every run fake AND would make
        `X-Synthetic-User` live, which is the thing this script exists to avoid
        needing.

`.env` is loaded by `brief_crew/__init__.py` with `override=True`, so anything
it declares wins over the shell. It declares none of the five names above
(measured: `grep -o '^[A-Za-z_][A-Za-z0-9_]*' .env`), so they are safe to
export; `OPENROUTER_API_KEY` and the Langfuse keys arrive from the file as
normal.

ORDER, AND THE ONE THING THAT BITES
------------------------------------
Start this server FIRST and kill it LAST. `JwksCache` caches for
`AUTH_JWKS_CACHE_SECONDS` (3600) and an unknown `kid` forces exactly one
refetch, so a backend that outlives this process will start refusing tokens the
moment its cache turns over - with `token is not valid`, which names nothing.
A failed refresh keeps serving the previous keys, so the failure is delayed and
looks like an expiry rather than a missing server.

USAGE
-----
    # terminal 1 - the JWKS server, foreground until killed
    python scripts/observability/mint_identity.py serve --port 8093

    # terminal 2 - one token on stdout and nothing else
    $token = python scripts/observability/mint_identity.py token --ttl 3600
    curl -H "Authorization: Bearer $token" http://127.0.0.1:8094/api/builder/tools

    # a token whose signature has one byte flipped, to prove the check is real
    $bad = python scripts/observability/mint_identity.py token --tamper

    # the public document, for evidence. Public keys only; no private material.
    python scripts/observability/mint_identity.py jwks

THE KEY FILE
------------
`token` and `serve` are separate processes, so they must share a key. It is
written as PKCS#8 PEM to `--key-file`, whose default is under the OS temp
directory and deliberately NOT in the repository: this script refuses a path
inside the repo root, because a private key committed by accident is a worse
outcome than an inconvenient default. Delete it when the proof session ends.
Nothing here ever prints private key material or a token to a file.

Serves: the identity precondition for every paid proof run
(`docs/observability/evidence/proof/identity/README.md`).
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import repo_root  # noqa: E402

#: The one path `service/auth.py::JwksCache.url` builds. The others are served
#: as conveniences for a human with a browser and are never fetched by the app.
JWKS_PATH = "/api/auth/jwks"
ALIAS_PATHS = ("/jwks", "/.well-known/jwks.json")

#: Ed25519 is the only algorithm `config.AUTH_JWT_ALGORITHMS` allows, and that
#: allowlist is what stops the `alg: none` and HMAC-confusion forgeries
#: `test_auth_jwt.py` pins. Nothing here may widen it.
ALGORITHM = "EdDSA"
DEFAULT_KID = "proof-identity-1"
DEFAULT_SUBJECT = "proof-runner"
DEFAULT_PORT = 8093
DEFAULT_TTL_SECONDS = 900


def default_key_path() -> Path:
    """Outside the repository, on purpose. See THE KEY FILE above."""

    base = os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp"
    return Path(base) / "brief-crew-proof-identity" / "ed25519.pem"


def _refuse_key_inside_repo(path: Path) -> None:
    root = repo_root()
    try:
        path.resolve().relative_to(root)
    except ValueError:
        return
    raise SystemExit(
        f"refusing to keep a private key inside the repository ({path}). "
        f"Use the default ({default_key_path()}) or another path outside "
        f"{root}."
    )


def load_or_create_key(path: Path) -> Ed25519PrivateKey:
    """The same key across `serve` and `token`, minted once.

    A fresh key per process would publish one public half and sign with
    another, and the failure - `token was signed by an unknown key`, after one
    wasted refetch - reads exactly like a rotation bug.
    """

    _refuse_key_inside_repo(path)
    if path.is_file():
        loaded = serialization.load_pem_private_key(
            path.read_bytes(), password=None
        )
        if not isinstance(loaded, Ed25519PrivateKey):
            raise SystemExit(
                f"{path} is not an Ed25519 private key; {ALGORITHM} is the only "
                "algorithm this service accepts"
            )
        return loaded

    private = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    # Create with owner-only permissions where the platform honours them, and
    # never widen an existing file's.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, pem)
    finally:
        os.close(fd)
    print(f"minted a new Ed25519 key at {path}", file=sys.stderr)
    return private


def jwks_document(public: Ed25519PublicKey, *, kid: str) -> dict[str, Any]:
    """The document Better Auth publishes, built the way the tests build it.

    `JwksCache._refresh` feeds each entry to `jwt.PyJWK(entry).key`, so the
    entry has to be a real JWK - `kty: OKP`, `crv: Ed25519`, `x` - and not a
    hand-rolled dictionary that merely looks like one.
    """

    entry = json.loads(jwt.algorithms.OKPAlgorithm.to_jwk(public))
    entry.update({"kid": kid, "alg": ALGORITHM, "use": "sig"})
    return {"keys": [entry]}


def mint(
    private: Ed25519PrivateKey,
    *,
    issuer: str,
    subject: str,
    ttl_seconds: int,
    kid: str,
    email: str | None = None,
    name: str | None = None,
) -> str:
    """One token, with exactly the claims `verify_token` requires.

    `options={"require": ["exp", "iss", "aud", "sub"]}` is the server's list;
    `iat` is added because a real Better Auth token carries one and the leeway
    test in `test_auth_jwt.py` is about it. `aud` is the issuer because
    `verify_token` passes `AUTH_BASE_URL` as both - this API is its own
    audience, which is what stops a token minted for some other service being
    replayed here.
    """

    now = int(time.time())
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": issuer,
        "sub": subject,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if email:
        claims["email"] = email
    if name:
        claims["name"] = name
    # The `kid` header is not optional: `JwksCache.key_for` raises
    # "token carries no key id" before it will even look at the cache.
    return jwt.encode(claims, private, algorithm=ALGORITHM, headers={"kid": kid})


def tamper(token: str) -> str:
    """Flip one bit of the signature, leaving everything else intact.

    The point of offering this is that a proof which only ever sends a GOOD
    token cannot tell "the signature was checked" from "no signature was
    checked". The header and payload are untouched, so the `kid` still
    resolves, the claims still parse, the expiry is still in the future - the
    only thing wrong is the 64 bytes at the end.
    """

    head, payload, signature = token.split(".")
    raw = bytearray(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)))
    raw[-1] ^= 0x01
    flipped = base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode()
    return f"{head}.{payload}.{flipped}"


class _JwksHandler(BaseHTTPRequestHandler):
    """One route, three spellings, and a log line per fetch.

    The log is on stderr and is evidence: it is how a verifier tells "the
    backend verified this token against my keys" from "the backend had them
    cached from a previous life".
    """

    server_version = "proof-identity/1.0"
    document: dict[str, Any] = {}

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        path = self.path.split("?", 1)[0].rstrip("/") or "/"
        if path == JWKS_PATH or path in ALIAS_PATHS:
            body = json.dumps(self.document).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps(
            {"error": "not found", "jwks": JWKS_PATH}
        ).encode("utf-8")
        self.send_response(404)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(
            "%s  %s\n" % (time.strftime("%H:%M:%S"), fmt % args)
        )
        sys.stderr.flush()


def command_serve(args: argparse.Namespace) -> int:
    private = load_or_create_key(Path(args.key_file))
    issuer = args.issuer or f"http://127.0.0.1:{args.port}"
    _JwksHandler.document = jwks_document(private.public_key(), kid=args.kid)

    server = ThreadingHTTPServer(("127.0.0.1", args.port), _JwksHandler)
    print(
        "\n".join(
            (
                f"JWKS   http://127.0.0.1:{args.port}{JWKS_PATH}",
                f"issuer {issuer}   (set AUTH_BASE_URL to exactly this)",
                f"kid    {args.kid}",
                f"key    {args.key_file}   (private; outside the repo; delete after)",
                "",
                "Start the backend AFTER this and kill it BEFORE this: the app "
                "caches these keys for AUTH_JWKS_CACHE_SECONDS and a failed "
                "refresh keeps serving the stale set, so the failure is late "
                "and reads like an expiry.",
                "",
            )
        ),
        file=sys.stderr,
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def command_token(args: argparse.Namespace) -> int:
    private = load_or_create_key(Path(args.key_file))
    issuer = args.issuer or f"http://127.0.0.1:{args.port}"
    token = mint(
        private,
        issuer=issuer,
        subject=args.sub,
        ttl_seconds=args.ttl,
        kid=args.kid,
        email=args.email,
        name=args.name,
    )
    if args.tamper:
        token = tamper(token)
    # stdout carries the token and nothing else, so `$t = python ... token`
    # is a usable idiom. Everything explanatory goes to stderr.
    print(token)
    return 0


def command_jwks(args: argparse.Namespace) -> int:
    private = load_or_create_key(Path(args.key_file))
    print(json.dumps(jwks_document(private.public_key(), kid=args.kid), indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    # The four shared options are declared on a PARENT and inherited by each
    # subcommand rather than sitting on the top-level parser. Put them in both
    # places and argparse's subparser defaults silently overwrite a value given
    # before the subcommand - `--port 8093 serve` would bind 8093 and issue
    # tokens for the default port, which is a mismatch nothing would name.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--key-file",
        default=str(default_key_path()),
        help="PKCS#8 PEM holding the Ed25519 private key; created if absent. "
        "Must be outside the repository (default: %(default)s)",
    )
    common.add_argument(
        "--kid",
        default=DEFAULT_KID,
        help="key id, in the JWKS entry and in every token header (default: %(default)s)",
    )
    common.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="port for the JWKS server, and the default issuer's port (default: %(default)s)",
    )
    common.add_argument(
        "--issuer",
        default=None,
        help="the value of AUTH_BASE_URL, used as both iss and aud "
        "(default: http://127.0.0.1:<port>)",
    )

    parser = argparse.ArgumentParser(
        prog="mint_identity.py",
        description=(
            "A local Ed25519 JWKS server and token minter, so a PAID backend "
            "can have a signed-in caller without a Google OAuth round trip. "
            "Shared options go AFTER the subcommand."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser(
        "serve", parents=[common], help="serve the JWKS document until killed"
    )
    serve.set_defaults(func=command_serve)

    token = sub.add_parser(
        "token", parents=[common], help="print ONE JWT to stdout and nothing else"
    )
    token.add_argument("--sub", default=DEFAULT_SUBJECT, help="the user id (default: %(default)s)")
    token.add_argument(
        "--ttl",
        type=int,
        default=DEFAULT_TTL_SECONDS,
        help="lifetime in seconds; 900 matches production, longer suits a proof "
        "session (default: %(default)s)",
    )
    token.add_argument("--email", default=None, help="optional email claim")
    token.add_argument("--name", default=None, help="optional display-name claim")
    token.add_argument(
        "--tamper",
        action="store_true",
        help="flip one signature byte, so a check can prove it verifies rather "
        "than merely accepts",
    )
    token.set_defaults(func=command_token)

    jwks = sub.add_parser(
        "jwks", parents=[common], help="print the PUBLIC JWKS document"
    )
    jwks.set_defaults(func=command_jwks)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
