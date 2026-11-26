import json
import socket
import threading
import urllib.request

ORIG_GETADDRINFO = socket.getaddrinfo
DNS_CACHE: dict[str, str] = {}
_DNS_LOCK = threading.Lock()


def is_nhentai_host(host: str) -> bool:
    h = host.lower()
    return h == "nhentai.net" or h.endswith(".nhentai.net")


def _resolve_doh(host: str) -> str | None:
    with _DNS_LOCK:
        if host in DNS_CACHE:
            return DNS_CACHE[host]

    try:
        req = urllib.request.Request(
            f"https://1.1.1.1/dns-query?name={host}&type=A",
            headers={"accept": "application/dns-json"},
        )
        with urllib.request.urlopen(req, timeout=5) as res:
            data = json.loads(res.read())
            ips = [ans["data"] for ans in data.get("Answer", []) if ans.get("type") == 1]
            if ips:
                with _DNS_LOCK:
                    DNS_CACHE[host] = ips[0]
                return ips[0]
    except Exception:
        pass
    return None


def enable_doh_resolver():
    def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if isinstance(host, str) and is_nhentai_host(host):
            ip = _resolve_doh(host)
            if ip:
                return ORIG_GETADDRINFO(ip, port, family, type, proto, flags)
        return ORIG_GETADDRINFO(host, port, family, type, proto, flags)

    socket.getaddrinfo = custom_getaddrinfo
