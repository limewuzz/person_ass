"""Opt-in adapters. An effect with an uncertain response MUST be reconciled.
Receipt SHA hashes the canonical receipt descriptor, never unobserved PDF/weight bytes.
AI/compute/implementation/WeChat are unavailable until a reviewed adapter is added.
"""

import hashlib
import json
import re
import subprocess
import sys
from urllib.parse import urlencode
from mw_io import private_file, request_json, request_bytes, TransportError


class Unavailable(Exception):
    pass


class UnknownOutcome(Exception):
    pass


def receipt(uri, descriptor, mode="LIVE"):
    raw = json.dumps(
        descriptor, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()
    return {
        "uri": uri,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_size": len(raw),
        "source_mode": mode,
    }


def execute(item, config, writes=False):
    if item["mode"] == "SIMULATE":
        return receipt(
            "mock://fanout/" + item["id"],
            {"simulation": True, "delivery_id": item["id"], "input": item["input"]},
            "MOCK",
        )
    target = item["target"]
    c = config.get(target)
    if not writes or not c or c.get("enabled") is not True:
        raise Unavailable("connector_not_enabled")
    marker = "mw-fanout:" + item["id"]
    text = item["input"][:4000]
    if target == "reminders":
        if sys.platform != "darwin" or not c.get("list"):
            raise Unavailable("mac_reminders_unavailable")
        # Values travel via argv; never interpolate user text into AppleScript.
        code = """on run argv
set listName to item 1 of argv
set marker to item 2 of argv
set noteText to item 3 of argv
tell application "Reminders"
set matches to lists whose name is listName
if (count of matches) is not 1 then error "Explicit existing reminders list required"
set destination to item 1 of matches
repeat with r in reminders of destination
if (body of r) contains marker then return id of r
end repeat
set r to make new reminder at end of reminders of destination with properties {name:"MagicWorkshop follow-up", body:marker & linefeed & noteText}
return id of r
end tell
end run"""
        try:
            result = (
                subprocess.run(
                    ["osascript", "-e", code, c["list"], marker, text],
                    capture_output=True,
                    timeout=25,
                    check=True,
                )
                .stdout.decode()
                .strip()
            )
        except (subprocess.SubprocessError, OSError):
            raise UnknownOutcome("reminders_result_unknown") from None
        return receipt(
            (
                result
                if result.startswith("x-apple-reminderkit://")
                else "reminders://" + item["id"]
            ),
            {"delivery_id": item["id"], "reminder_id": result},
        )
    if target not in {"notion", "drive", "github"}:
        raise Unavailable("adapter_not_implemented")
    token = private_file(c["token_file"], 16384).decode()
    headers = {"Authorization": "Bearer " + token}

    def read(url):
        return request_json(url, headers=headers)

    def write(url, body, extra=None):
        try:
            return request_json(url, body, {**headers, **(extra or {})}, "POST")
        except TransportError:
            raise UnknownOutcome("external_write_result_unknown") from None

    if target == "notion":
        parent = c.get("parent_page_id", "")
        if not re.fullmatch(r"[a-fA-F0-9-]{32,36}", parent):
            raise Unavailable("notion_parent_required")
        headers["Notion-Version"] = "2022-06-28"
        # A marker is visible in the page title for operator/provider reconciliation.
        existing = write(
            "https://api.notion.com/v1/search",
            {"query": marker, "filter": {"value": "page", "property": "object"}},
        )
        found = next(
            (
                x
                for x in existing.get("results", [])
                if x.get("parent", {}).get("page_id", "").replace("-", "")
                == parent.replace("-", "")
            ),
            None,
        )
        page = found or write(
            "https://api.notion.com/v1/pages",
            {
                "parent": {"page_id": parent},
                "properties": {"title": {"title": [{"text": {"content": marker}}]}},
                "children": [
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {"type": "text", "text": {"content": text[:1900]}}
                            ]
                        },
                    }
                ],
            },
        )
        return receipt(
            page["url"],
            {
                "delivery_id": item["id"],
                "page_id": page["id"],
                "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
            },
        )
    if target == "github":
        repo = c.get("repository", "")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise Unavailable("github_repository_required")
        # Issues only. No automatic branch push, code execution or repository mutation beyond this issue.
        result = read(
            "https://api.github.com/search/issues?"
            + urlencode({"q": f'repo:{repo} "{marker}" in:body'})
        )
        issue = next(
            (x for x in result.get("items", []) if marker in x.get("body", "")), None
        )
        issue = issue or write(
            f"https://api.github.com/repos/{repo}/issues",
            {
                "title": "MagicWorkshop implementation request",
                "body": f"<!-- {marker} -->\n{text}",
            },
        )
        return receipt(
            issue["html_url"], {"delivery_id": item["id"], "issue_id": issue["id"]}
        )
    parent = c.get("folder_id", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,200}", parent):
        raise Unavailable("drive_folder_required")
    query = f"'{parent}' in parents and trashed = false and appProperties has {{ key='mw_delivery_id' and value='{item['id']}' }}"
    found = read(
        "https://www.googleapis.com/drive/v3/files?"
        + urlencode({"q": query, "fields": "files(id,webViewLink)"})
    ).get("files", [])
    if found:
        file = found[0]
    else:
        # Archive the supplied intent as JSON; do not claim unseen PDF or checkpoint bytes were copied.
        metadata = {
            "name": marker + ".json",
            "parents": [parent],
            "appProperties": {"mw_delivery_id": item["id"]},
        }
        boundary = "mw_" + item["id"].replace("-", "")
        data = b"".join(
            [
                (
                    "--"
                    + boundary
                    + "\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
                ).encode(),
                json.dumps(metadata).encode(),
                (
                    "\r\n--" + boundary + "\r\nContent-Type: application/json\r\n\r\n"
                ).encode(),
                json.dumps(
                    {
                        "delivery_id": item["id"],
                        "input": text,
                        "parameters": item["parameters"],
                    },
                    ensure_ascii=False,
                ).encode(),
                ("\r\n--" + boundary + "--\r\n").encode(),
            ]
        )
        try:
            file = request_bytes(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id,webViewLink",
                data,
                {**headers, "Content-Type": "multipart/related; boundary=" + boundary},
                "POST",
            )
        except TransportError:
            raise UnknownOutcome("drive_write_result_unknown") from None
    return receipt(
        file.get(
            "webViewLink", "https://drive.google.com/file/d/" + file["id"] + "/view"
        ),
        {
            "delivery_id": item["id"],
            "file_id": file["id"],
            "content_kind": "intent-json",
        },
    )
