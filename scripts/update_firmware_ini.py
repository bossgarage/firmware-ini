#!/usr/bin/env python3
"""Import dated BossECU INI snapshots from the public EpicEFI firmware index."""

from __future__ import annotations

import hashlib
import html.parser
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date
from pathlib import Path


BASE_URL = "https://www.epicefi.com/firmware/fw.php/"
ALLOWED_HOST = urllib.parse.urlsplit(BASE_URL).hostname
BOARDS = (
    "BossECU_48",
    "BossECU_Brain_F4",
    "BossECU_Brain_H7",
)
REQUEST_TIMEOUT_SECONDS = 45
MAX_ATTEMPTS = 4
USER_AGENT = "BossECU-firmware-ini-updater/1.0 (+https://github.com/bossgarage/firmware-ini)"

DATE_IN_PATH = re.compile(r"(?:^|/)(20\d{2}-\d{2}-\d{2})/?$")
DATE_IN_FILENAME = re.compile(r"(?<!\d)(20\d{2})\.(\d{2})\.(\d{2})(?!\d)")
SIGNATURE_LINE = re.compile(
    r'^\s*signature\s*=\s*"([^"\r\n]+)"\s*$', re.IGNORECASE | re.MULTILINE
)
SAFE_SIGNATURE = re.compile(r"^[A-Za-z0-9 _.()-]+$")


class HrefParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for key, value in attrs:
            if key.lower() == "href" and value:
                self.hrefs.append(value)


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(MAX_ATTEMPTS):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(f"HTTP {error.code} while downloading {url}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(f"Could not download {url}: {error}") from error
        time.sleep(2**attempt)
    raise AssertionError("unreachable retry loop")


def listing_links(url: str) -> list[str]:
    raw_html = fetch(url).decode("utf-8", errors="replace")
    parser = HrefParser()
    parser.feed(raw_html)
    links: list[str] = []
    for href in parser.hrefs:
        resolved = urllib.parse.urljoin(url, href)
        parts = urllib.parse.urlsplit(resolved)
        if parts.scheme == "https" and parts.hostname == ALLOWED_HOST:
            links.append(resolved)
    return links


def published_dates() -> list[date]:
    found: set[date] = set()
    for link in listing_links(BASE_URL):
        path = urllib.parse.urlsplit(link).path
        match = DATE_IN_PATH.search(path)
        if match:
            try:
                found.add(date.fromisoformat(match.group(1)))
            except ValueError:
                continue
    if not found:
        raise RuntimeError("No dated firmware directories found on the EpicEFI index")
    return sorted(found)


def newest_local_date(board_dir: Path) -> date:
    candidates: list[date] = []
    for ini_path in board_dir.glob("*.ini"):
        match = DATE_IN_FILENAME.search(ini_path.name)
        if not match:
            continue
        try:
            candidates.append(date(*(int(part) for part in match.groups())))
        except ValueError:
            continue
    if not candidates:
        raise RuntimeError(f"No dated INI snapshots found in {board_dir.name}")
    return max(candidates)


def board_ini_url(release_date: date, board: str, day_links: list[str]) -> str | None:
    expected_zip = f"epicefi_bundle_{board}.zip"
    matching_zips = [
        link
        for link in day_links
        if urllib.parse.unquote(urllib.parse.urlsplit(link).path).rstrip("/").endswith(
            "/" + expected_zip
        )
    ]
    if not matching_zips:
        return None
    if len(matching_zips) != 1:
        raise RuntimeError(
            f"{release_date}: expected one {expected_zip}, found {len(matching_zips)}"
        )

    snapshot_url = urllib.parse.urljoin(
        matching_zips[0].rstrip("/") + "/",
        f"epicefi.snapshot.{board}/",
    )
    ini_links = [
        link
        for link in listing_links(snapshot_url)
        if urllib.parse.unquote(urllib.parse.urlsplit(link).path)
        .rsplit("/", 1)[-1]
        .lower()
        .startswith("rusefi")
        and urllib.parse.urlsplit(link).path.lower().endswith(".ini")
    ]
    if len(ini_links) != 1:
        raise RuntimeError(
            f"{release_date} {board}: expected one rusefi*.ini in the snapshot, "
            f"found {len(ini_links)}"
        )
    return ini_links[0]


def signature_filename(data: bytes, board: str, release_date: date) -> str:
    text = data.decode("utf-8-sig", errors="replace")
    signatures = SIGNATURE_LINE.findall(text)
    if len(signatures) != 1:
        raise RuntimeError(
            f"{release_date} {board}: expected one INI signature, found {len(signatures)}"
        )
    signature = signatures[0].strip()
    if not signature.lower().startswith("rusefi"):
        raise RuntimeError(f"{release_date} {board}: unexpected signature {signature!r}")
    if board not in signature:
        raise RuntimeError(
            f"{release_date}: signature {signature!r} does not identify board {board}"
        )
    if not SAFE_SIGNATURE.fullmatch(signature):
        raise RuntimeError(f"Unsafe characters in INI signature {signature!r}")
    return f"{signature}.ini"


def run() -> int:
    root = Path(__file__).resolve().parents[1]
    dates = published_dates()
    latest_by_board = {
        board: newest_local_date(root / board) for board in BOARDS
    }
    print("Latest local snapshots:")
    for board in BOARDS:
        print(f"  {board}: {latest_by_board[board].isoformat()}")

    day_listing_cache: dict[date, list[str]] = {}
    staged_by_target: dict[Path, tuple[Path, str]] = {}
    with tempfile.TemporaryDirectory(prefix="firmware-ini-") as temporary_dir:
        temporary_root = Path(temporary_dir)
        for board in BOARDS:
            candidates = [d for d in dates if d > latest_by_board[board]]
            for release_date in candidates:
                if release_date not in day_listing_cache:
                    date_url = urllib.parse.urljoin(
                        BASE_URL, f"{release_date.isoformat()}/"
                    )
                    day_listing_cache[release_date] = listing_links(date_url)
                ini_url = board_ini_url(
                    release_date, board, day_listing_cache[release_date]
                )
                if ini_url is None:
                    continue

                data = fetch(ini_url)
                filename = signature_filename(data, board, release_date)
                target = root / board / filename
                digest = hashlib.sha256(data).hexdigest()

                if target.exists():
                    existing_digest = hashlib.sha256(target.read_bytes()).hexdigest()
                    if existing_digest == digest:
                        print(f"Already present: {board}/{filename}")
                        continue
                    raise RuntimeError(
                        f"Refusing to overwrite {board}/{filename}: "
                        "the same signature has different contents"
                    )

                previous = staged_by_target.get(target)
                if previous:
                    if previous[1] != digest:
                        raise RuntimeError(
                            f"Two different snapshots map to {board}/{filename}"
                        )
                    continue

                staged_path = temporary_root / f"{len(staged_by_target):04d}.ini"
                staged_path.write_bytes(data)
                staged_by_target[target] = (staged_path, digest)
                print(
                    f"Found {board}/{filename} from {release_date.isoformat()}"
                )

        if not staged_by_target:
            print("No new INI snapshots found.")
            return 0

        for target, (staged_path, _) in staged_by_target.items():
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_path, target)
            print(f"Added {target.relative_to(root)}")

    print(f"Added {len(staged_by_target)} new INI snapshot(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
