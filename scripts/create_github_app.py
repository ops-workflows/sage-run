"""Register an organization GitHub App using GitHub's manifest handshake."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import secrets
import tempfile
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

PERMISSIONS = {"contents": "write", "issues": "write", "metadata": "read", "pull_requests": "write"}


def parse_organization(value: str) -> tuple[str, str]:
    value = value.strip()
    if "://" not in value:
        value = "https://" + value
    parsed = urlsplit(value)
    parts = parsed.path.strip("/").split("/")
    if parts[0] == "organizations":
        parts = parts[1:]
    valid_path = len(parts) == 1 or (len(parts) in (3, 4) and parts[1:3] == ["settings", "apps"])
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or not valid_path
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", parts[0])
        or not re.fullmatch(r"[A-Za-z0-9.-]+(?::[0-9]+)?", parsed.netloc)
    ):
        raise ValueError("Use an HTTPS organization URL, such as https://github.com/acme or https://ghes.example/acme.")
    return f"https://{parsed.netloc.lower()}", parts[0]


def api_base_url(web_base_url: str) -> str:
    return "https://api.github.com" if web_base_url == "https://github.com" else web_base_url + "/api/v3"


def build_manifest(name: str, homepage: str, redirect_url: str) -> dict:
    if not name.strip() or len(name) > 34 or any(ord(character) < 32 for character in name):
        raise ValueError("App name must contain 1-34 characters without control characters.")
    return {
        "name": name.strip(),
        "url": homepage,
        "redirect_url": redirect_url,
        "public": False,
        "hook_attributes": {"url": homepage, "active": False},
        "default_permissions": dict(PERMISSIONS),
        "default_events": [],
        "request_oauth_on_install": False,
    }


def convert_manifest(web_base_url: str, code: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", code):
        raise ValueError("Invalid manifest conversion code.")
    request = Request(  # noqa: S310
        f"{api_base_url(web_base_url)}/app-manifests/{code}/conversions",
        data=b"{}",
        headers={"Accept": "application/vnd.github+json", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            return json.load(response)
    except HTTPError as error:
        raise RuntimeError(f"Manifest conversion failed (HTTP {error.code}); no response body was printed.") from None
    except URLError:
        raise RuntimeError("Manifest conversion failed; check host connectivity and TLS trust.") from None


def write_private_file(destination: Path, content: str) -> None:
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(content)


def save_credentials(directory: Path, web_base_url: str, organization: str, payload: dict) -> None:
    if not payload.get("id") or not payload.get("pem") or not payload.get("slug"):
        raise ValueError("GitHub's response is missing the App ID, slug, or private key.")
    write_private_file(directory / "credentials.json", json.dumps(payload, indent=2) + "\n")
    write_private_file(directory / "private-key.pem", payload["pem"])
    connection = {
        "web_base_url": web_base_url,
        "api_base_url": api_base_url(web_base_url),
        "app_id": payload["id"],
        "installation_id": None,
        "private_key_secret": "github_app_private_key",
        "organization": organization,
        "settings_url": f"{web_base_url}/organizations/{organization}/settings/apps/{payload['slug']}",
        "installation_url": payload["html_url"].rstrip("/") + "/installations/new",
    }
    write_private_file(directory / "connection.json", json.dumps(connection, indent=2) + "\n")


class RegistrationServer(HTTPServer):
    code: str | None = None

    def __init__(self, web_base_url: str, organization: str, name: str, port: int):
        state = secrets.token_urlsafe(32)
        server = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 5

            def log_message(self, message_format, *args):
                pass

            def do_GET(self):  # noqa: N802
                if self.headers.get("Host") != server.authority:
                    self.reply(403, "Invalid host.")
                    return
                parsed = urlsplit(self.path)
                if parsed.path == server.start_path and not parsed.query:
                    action = f"{web_base_url}/organizations/{organization}/settings/apps/new?" + urlencode(
                        {"state": state}
                    )
                    manifest = build_manifest(name, f"{web_base_url}/{organization}", server.callback_url)
                    self.reply(
                        200,
                        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Register GitHub App</title>'
                        f"<h1>{html.escape(name)}</h1>"
                        f'<form method="post" action="{html.escape(action, quote=True)}">'
                        '<input type="hidden" name="manifest" value="'
                        + html.escape(json.dumps(manifest), quote=True)
                        + '"><button type="submit">Continue to GitHub</button></form></html>',
                    )
                elif parsed.path == "/callback":
                    query = parse_qs(parsed.query)
                    if (
                        len(query.get("state", [])) != 1
                        or not query["state"][0].isascii()
                        or not secrets.compare_digest(query["state"][0], state)
                        or len(query.get("code", [])) != 1
                        or not re.fullmatch(r"[A-Za-z0-9_-]{1,200}", query["code"][0])
                        or server.code is not None
                    ):
                        self.reply(400, "Invalid or expired registration callback.")
                        return
                    server.code = query["code"][0]
                    self.reply(200, "Registration received. Return to the terminal for credential storage.")
                else:
                    self.reply(404, "Not found.")

            def reply(self, status_code: int, body: str):
                encoded = body.encode("utf-8")
                self.send_response(status_code)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header(
                    "Content-Security-Policy", f"default-src 'none'; form-action {web_base_url}; frame-ancestors 'none'"
                )
                self.end_headers()
                self.wfile.write(encoded)

        super().__init__(("127.0.0.1", port), Handler)
        self.authority = f"127.0.0.1:{self.server_port}"
        self.start_path = "/register/" + state
        self.start_url = f"http://{self.authority}{self.start_path}"
        self.callback_url = f"http://{self.authority}/callback"

    def wait_for_code(self, timeout: int) -> str:
        deadline = time.monotonic() + timeout
        while self.code is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Registration timed out; no credentials were retrieved.")
            self.timeout = min(remaining, 1)
            self.handle_request()
        return self.code


def create_output_directory(destination: str | None, web_base_url: str, organization: str) -> Path:
    if destination:
        directory = Path(destination).expanduser().absolute()
        directory.parent.mkdir(parents=True, exist_ok=True)
        directory.mkdir(mode=0o700)
        return directory
    root = Path.home() / ".config" / "sage-run" / "github-apps" / urlsplit(web_base_url).netloc
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return Path(tempfile.mkdtemp(prefix=f"{organization}-", dir=root))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--org", help="Organization URL on GitHub.com or GHES; prompted when omitted")
    parser.add_argument("--name", help="GitHub App name; prompted when omitted")
    parser.add_argument("--output-dir", help="New private output directory; existing directories are never overwritten")
    parser.add_argument("--port", type=int, default=8765, help="Loopback port (default: 8765; 0 selects a free port)")
    parser.add_argument("--timeout", type=int, default=600, help="Browser approval timeout in seconds (default: 600)")
    parser.add_argument("--no-browser", action="store_true", help="Print the local URL without opening a browser")
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.port <= 65535 or not 1 <= args.timeout <= 3600:
            raise ValueError("Port must be 0-65535 and timeout must be 1-3600 seconds.")
        base, organization = parse_organization(args.org or input("GitHub organization URL: "))
        name = (args.name or input("GitHub App name: ")).strip()
        build_manifest(name, f"{base}/{organization}", "http://127.0.0.1/callback")
        print(f"Register {name!r} owned by {organization} on {base}.")
        print("Permissions: Contents, Issues, Pull Requests = write; Metadata = read.")
        print("Private to this organization; no webhook events or user OAuth authorization.")
        if input("Continue to browser registration? [y/N]: ").strip().lower() not in {"y", "yes"}:
            print("Cancelled; no App was created.")
            return 0
        with RegistrationServer(base, organization, name, args.port) as server:
            directory = create_output_directory(args.output_dir, base, organization)
            print(f"Credentials will be saved under: {directory}")
            print(f"Open: {server.start_url}")
            print("Continue to GitHub, review the name, then choose Create GitHub App.")
            print("On SSH, forward the same loopback port before opening this URL in your local browser.")
            if not args.no_browser and not os.environ.get("SSH_CONNECTION"):
                try:
                    webbrowser.open(server.start_url)
                except webbrowser.Error:
                    print("Browser could not be opened automatically; use the URL above.")
            code = server.wait_for_code(args.timeout)
        payload = convert_manifest(base, code)
        save_credentials(directory, base, organization, payload)
        print(f"Created App ID: {payload['id']}")
        print(f"Private key: {directory / 'private-key.pem'}")
        print(f"All credentials (including client/webhook secrets): {directory / 'credentials.json'}")
        print(f"Connection metadata: {directory / 'connection.json'}")
        print(f"Install: {payload['html_url'].rstrip('/')}/installations/new")
        print("Choose Only select repositories. Copy the installation ID from the resulting installation URL.")
        print("Set that ID in your GitHub connection and encrypt private-key.pem with scripts/set_secret.py.")
        return 0
    except (ValueError, RuntimeError, OSError) as error:
        print(f"Error: {error}")
        print("If browser registration succeeded, inspect App settings before retrying; do not create a duplicate.")
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Any already-registered App is not deleted.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
