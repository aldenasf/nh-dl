import json
import socket
import urllib.request

ORIG_GETADDRINFO = socket.getaddrinfo
DNS_CACHE = {}

def enable_doh_resolver():
    def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if host in ('nhentai.net', 'i.nhentai.net', 't.nhentai.net'):
            if host not in DNS_CACHE:
                try:
                    req = urllib.request.Request(
                        f'https://1.1.1.1/dns-query?name={host}&type=A',
                        headers={'accept': 'application/dns-json'}
                    )
                    with urllib.request.urlopen(req, timeout=5) as res:
                        data = json.loads(res.read())
                        ips = [ans['data'] for ans in data.get('Answer', []) if ans['type'] == 1]
                        if ips:
                            DNS_CACHE[host] = ips[0]
                except Exception:
                    pass
            if host in DNS_CACHE:
                return ORIG_GETADDRINFO(DNS_CACHE[host], port, family, type, proto, flags)
        return ORIG_GETADDRINFO(host, port, family, type, proto, flags)

    socket.getaddrinfo = custom_getaddrinfo
