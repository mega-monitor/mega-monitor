import re
import json
import base64
from dataclasses import dataclass
from typing import List, Dict, Tuple, Optional
import requests
import logging
import os
from Crypto.Cipher import AES

logger = logging.getLogger(__name__)

class MegaAPIError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(f"MEGA API error {code}: {message}")
        self.code = code
        self.message = message

@dataclass
class InvalidLinkReport:
    name: str
    url: str
    code: int
    reason: str

class NoValidLinksError(ValueError):
    def __init__(self, reports: List[InvalidLinkReport]):
        super().__init__("No valid MEGA links defined in environment")
        self.reports = reports


_ERROR_MAP = {
    -2: "EARGS: Invalid arguments",
    -3: "EAGAIN: Try again (temporary)",
    -4: "ERATELIMIT: Rate limited",
    -9: "ENOENT: Folder/file not found (removed or never existed)",
    -11: "EACCESS: Access denied (permission revoked)",
    -14: "EKEY: Invalid decryption key",
    -16: "EBLOCKED: Access blocked/banned",
    -17: "EOVERQUOTA: Quota exceeded",
    -18: "ETEMPUNAVAIL: Temporarily unavailable",
}


def _decode_cs_error(first) -> Optional[int]:
    if isinstance(first, int):
        return first
    if isinstance(first, dict) and isinstance(first.get("e"), int):
        return first["e"]
    return None


def get_mega_links() -> List[Dict[str, str]]:
    valid: List[Dict[str, str]] = []
    invalid: List[InvalidLinkReport] = []

    for key, url in os.environ.items():
        if not key.startswith("MEGA_LINK_"):
            continue
        name = key.removeprefix("MEGA_LINK_")
        try:
            root, key_b64 = parse_folder_url(url)
            _ = get_nodes(root)  # raises MegaAPIError for -9/-16 etc.
            valid.append({"name": name, "url": url})
        except MegaAPIError as e:
            logger.warning("MEGA returned error %s for %s: %s", e.code, root, e.message)
            invalid.append(InvalidLinkReport(name=name, url=url, code=e.code, reason=e.message))
        except Exception as e:
            logger.exception("Failed to validate %s", name)
            invalid.append(InvalidLinkReport(name=name, url=url, code=-1, reason=str(e)))

    if not valid:
        raise NoValidLinksError(invalid)

    return valid


def sanitize(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", name)


def parse_folder_url(url: str) -> Tuple[str, str]:
    logger.debug("Parsing folder URL: %s", url)
    match = re.search(r"mega\.[^/]+/folder/([0-9A-Za-z_-]+)#([0-9A-Za-z_-]+)", url)
    if not match:
        match = re.search(r"mega\.[^/]+/#F!([0-9A-Za-z_-]+)!([0-9A-Za-z_-]+)", url)
        logger.debug("Parsed URL → root=%s key=%s", match.group(1), match.group(2))
    if not match:
        raise ValueError(f"Invalid MEGA folder URL: {url}")
    return match.group(1), match.group(2)


def base64_url_decode(data: str) -> bytes:
    data += "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data)


def base64_to_a32(data: str) -> Tuple[int, ...]:
    raw = base64_url_decode(data)
    return tuple(int.from_bytes(raw[i : i + 4], "big") for i in range(0, len(raw), 4))


def decrypt_key(
    cipher: Tuple[int, ...], shared_key: Tuple[int, ...]
) -> Tuple[int, ...]:
    key_bytes = b"".join(x.to_bytes(4, "big") for x in shared_key)
    cipher_bytes = b"".join(x.to_bytes(4, "big") for x in cipher)
    aes = AES.new(key_bytes, AES.MODE_ECB)
    plain = aes.decrypt(cipher_bytes)
    return tuple(
        int.from_bytes(plain[i : i + 4], "big") for i in range(0, len(plain), 4)
    )


def decrypt_attr(attr_bytes: bytes, key: Tuple[int, ...]) -> Dict:
    aes_key = b"".join(x.to_bytes(4, "big") for x in key[:4])
    aes = AES.new(aes_key, AES.MODE_CBC, iv=b"\0" * 16)
    decrypted = aes.decrypt(attr_bytes)
    text = decrypted.rstrip(b"\0").decode("utf-8", errors="ignore")
    json_part = text[text.find("{") : text.rfind("}") + 1]
    return json.loads(json_part)


def get_nodes(root: str) -> List[Dict]:
    logger.debug("Fetching nodes for root %s", root)
    resp = requests.post(
        "https://g.api.mega.co.nz/cs",
        params={"id": 0, "n": root},
        data=json.dumps([{"a": "f", "c": 1, "ca": 1, "r": 1}]),
        timeout=(3.05, 30),
    )
    try:
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        logger.exception("MEGA API error while fetching nodes for %s", root)
        raise

    def _raise(code: int):
        msg = _ERROR_MAP.get(code, "Unknown error")
        raise MegaAPIError(code, msg)

    if isinstance(payload, int):
        _raise(payload)

    if isinstance(payload, list):
        if not payload:
            raise MegaAPIError(-1, "Empty MEGA response")
        first = payload[0]
        if isinstance(first, int):
            _raise(first)
        if isinstance(first, dict) and isinstance(first.get("e"), int):
            _raise(first["e"])
        if isinstance(first, dict) and "f" in first:
            f = first.get("f", [])
            if not isinstance(f, list):
                raise MegaAPIError(-1, "Malformed 'f' field")
            return f
        raise MegaAPIError(-1, f"Unexpected MEGA response object: {first!r}")

    raise MegaAPIError(
        -1, f"Unexpected MEGA response type: {type(payload).__name__} → {payload!r}"
    )


def decrypt_node(node: Dict, shared_key: Tuple[int, ...]) -> Dict:
    enc = node["k"].split(":")[-1]
    key = decrypt_key(base64_to_a32(enc), shared_key)
    if node.get("t") == 0:
        key = tuple(key[i] ^ key[i + 4] for i in range(4))
    attrs = decrypt_attr(base64_url_decode(node.get("a", "")), key)
    return {
        "h": node["h"],
        "p": node["p"],
        "name": attrs.get("n"),
        "type": node["t"],
        "size": node.get("s", 0),
    }


def build_paths(nodes: List[Dict], root: str) -> List[Dict]:
    lookup = {n["h"]: n for n in nodes}

    def resolve(h: str) -> str:
        if h == root or h not in lookup:
            return ""
        parent = resolve(lookup[h]["p"])
        return f"{parent}/{lookup[h]['name']}" if parent else lookup[h]["name"]

    return [
        {"h": n["h"], "path": resolve(n["h"]), "type": n["type"], "size": n.get("size")}
        for n in nodes
        if resolve(n["h"])
    ]
