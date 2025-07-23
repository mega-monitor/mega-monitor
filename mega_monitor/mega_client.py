import re
import json
import base64
from pathlib import Path
from typing import List, Dict, Tuple
import requests
import logging
import os
from Crypto.Cipher import AES

logger = logging.getLogger(__name__)

def get_mega_links() -> List[Dict[str, str]]:
    """
    Scan os.environ for all MEGA_LINK_<NAME>=<URL> entries
    and return only those that both parse and return a node list successfully.
    """
    valid_links: List[Dict[str, str]] = []
    prefix = "MEGA_LINK_"

    for key, val in os.environ.items():
        # only consider MEGA_LINK_ vars
        if not key.startswith(prefix):
            continue

        name = key[len(prefix):]
        url = val.strip()

        # empty?
        if not url:
            logger.warning("Environment variable %s is empty; skipping", key)
            continue

        # 1) parse to extract root & key
        try:
            root, key_bytes = parse_folder_url(url)
        except Exception as e:
            logger.error("Invalid MEGA URL for %s (%s): %s", name, url, e)
            continue

        # 2) smoke-test the API to ensure it exists/returns nodes
        try:
            get_nodes(root)
        except Exception as e:
            logger.error("Failed to fetch MEGA folder %s (%s): %s", name, url, e)
            continue

        # passed both checks—keep it
        logger.info("Registered & verified MEGA link %s → %s", name, url)
        valid_links.append({"name": name, "url": url})

    if not valid_links:
        logger.critical("No valid MEGA links found! Check your MEGA_LINK_* settings.")
        raise ValueError("No valid MEGA links defined in environment")

    return valid_links


def sanitize(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9_-]', '_', name)


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
    data += '=' * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode(data)


def base64_to_a32(data: str) -> Tuple[int, ...]:
    raw = base64_url_decode(data)
    return tuple(int.from_bytes(raw[i:i+4], 'big') for i in range(0, len(raw), 4))


def decrypt_key(cipher: Tuple[int,...], shared_key: Tuple[int,...]) -> Tuple[int,...]:
    key_bytes = b''.join(x.to_bytes(4, 'big') for x in shared_key)
    cipher_bytes = b''.join(x.to_bytes(4, 'big') for x in cipher)
    aes = AES.new(key_bytes, AES.MODE_ECB)
    plain = aes.decrypt(cipher_bytes)
    return tuple(int.from_bytes(plain[i:i+4], 'big') for i in range(0, len(plain), 4))


def decrypt_attr(attr_bytes: bytes, key: Tuple[int,...]) -> Dict:
    aes_key = b''.join(x.to_bytes(4, 'big') for x in key[:4])
    aes = AES.new(aes_key, AES.MODE_CBC, iv=b'\0'*16)
    decrypted = aes.decrypt(attr_bytes)
    text = decrypted.rstrip(b'\0').decode('utf-8', errors='ignore')
    json_part = text[text.find('{'): text.rfind('}')+1]
    return json.loads(json_part)


def get_nodes(root: str) -> List[Dict]:
    logger.debug("Fetching nodes for root %s", root)
    resp = requests.post(
        "https://g.api.mega.co.nz/cs",
        params={'id': 0, 'n': root},
        data=json.dumps([{'a':'f','c':1,'ca':1,'r':1}]),
        timeout=(3.05, 30)
    )
    try:
        resp.raise_for_status()
    except Exception:
        logger.exception("MEGA API error while fetching nodes for %s", root)
        raise
    return resp.json()[0].get('f', [])


def decrypt_node(node: Dict, shared_key: Tuple[int,...]) -> Dict:
    enc = node['k'].split(':')[-1]
    key = decrypt_key(base64_to_a32(enc), shared_key)
    if node.get('t') == 0:
        key = tuple(key[i] ^ key[i+4] for i in range(4))
    attrs = decrypt_attr(base64_url_decode(node.get('a', '')), key)
    return {
        'h': node['h'],
        'p': node['p'],
        'name': attrs.get('n'),
        'type': node['t'],
        'size': node.get('s', 0)
    }


def build_paths(nodes: List[Dict], root: str) -> List[Dict]:
    lookup = {n['h']: n for n in nodes}

    def resolve(h: str) -> str:
        if h == root or h not in lookup:
            return ''
        parent = resolve(lookup[h]['p'])
        return f"{parent}/{lookup[h]['name']}" if parent else lookup[h]['name']

    return [
        {'h': n['h'], 'path': resolve(n['h']), 'type': n['type'], 'size': n.get('size')}
        for n in nodes if resolve(n['h'])
    ]