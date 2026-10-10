"""Prepare a checksum-verified, minimally patched Maps build outside source files."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get("IECHO_MAPS_BUILD_DIR", ROOT / "runtime/build"))


def replace(path, old, new):
    text = path.read_text()
    if text.count(old) != 1:
        raise RuntimeError("Patch no longer matches pinned source: " + str(path))
    path.write_text(text.replace(old, new))


def main():
    BUILD.mkdir(parents=True, exist_ok=True)
    sources = json.loads((ROOT / "config/maps-sources.json").read_text())
    for source in sources:
        cache = BUILD / (source["name"] + ".tar.gz")
        data = cache.read_bytes() if cache.exists() else urllib.request.urlopen(source["url"], timeout=120).read()
        if hashlib.sha256(data).hexdigest() != source["sha256"]:
            raise RuntimeError("Source checksum mismatch: " + source["name"])
        cache.write_bytes(data)
        target = BUILD / source["name"]
        if target.exists():
            shutil.rmtree(target)
        target.mkdir()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            for member in archive.getmembers():
                parts = Path(member.name).parts[1:]
                if not parts:
                    continue
                if ".." in parts or member.issym() or member.islnk():
                    raise RuntimeError("Unsafe archive member")
                dest = target.joinpath(*parts)
                if member.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with archive.extractfile(member) as f:
                        dest.write_bytes(f.read())
        print("Verified source:", source["name"], source["commit"])
    dep = BUILD / "scrapemate/adapters/fetchers"
    replace(dep / "stealth/stealth.go", "\t\tsession.InsecureSkipVerify = true\n", "")
    browser = dep / "jshttp/jshttp.go"
    for flag in ["--ignore-certificate-errors", "--ignore-certificate-errors-spki-list", "--disable-web-security"]:
        text = browser.read_text()
        lines = [line for line in text.splitlines(True) if '"' + flag + '"' in line]
        if len(lines) != 1:
            raise RuntimeError("Browser patch mismatch: " + flag)
        replace(browser, lines[0], "")
    proxy = dep / "jshttp/local_proxy.go"
    replace(proxy, 'if username == "" || password == "" {\n\t\treturn nil, fmt.Errorf("username and password are required")', 'if (username == "") != (password == "") {\n\t\treturn nil, fmt.Errorf("provide both username and password, or neither")')
    replace(proxy, "if proxyType == ProxyTypeHTTP {\n\t\tupstream.User", 'if proxyType == ProxyTypeHTTP && username != "" {\n\t\tupstream.User')
    replace(proxy, 'auth:       base64.StdEncoding.EncodeToString([]byte(username + ":" + password)),', 'auth:       func() string { if username == "" { return "" }; return base64.StdEncoding.EncodeToString([]byte(username + ":" + password)) }(),')
    replace(proxy, "if proxyType == ProxyTypeSOCKS5 {\n\t\tauthProxy.socks5Auth", 'if proxyType == ProxyTypeSOCKS5 && username != "" {\n\t\tauthProxy.socks5Auth')
    replace(proxy, "if p.proxyType == ProxyTypeHTTP {\n\t\treq.Header.Set", 'if p.proxyType == ProxyTypeHTTP && p.auth != "" {\n\t\treq.Header.Set')
    replace(proxy, 'connectReq := fmt.Sprintf("CONNECT %s HTTP/1.1\\r\\nHost: %s\\r\\nProxy-Authorization: Basic %s\\r\\n\\r\\n",\n\t\tr.Host, r.Host, p.auth)', 'authHeader := ""\n\tif p.auth != "" { authHeader = "Proxy-Authorization: Basic " + p.auth + "\\r\\n" }\n\tconnectReq := fmt.Sprintf("CONNECT %s HTTP/1.1\\r\\nHost: %s\\r\\n%s\\r\\n", r.Host, r.Host, authHeader)')
    trust = BUILD / "trust"
    if trust.exists():
        shutil.rmtree(trust)
    trust.mkdir()
    (trust / ".keep").write_text("Public CA certificates only.\n")
    source_dir = Path("/usr/local/share/ca-certificates")
    if source_dir.is_dir():
        for cert in source_dir.glob("*.crt"):
            shutil.copyfile(cert, trust / cert.name)
    shutil.copyfile(ROOT / "config/Dockerfile.maps", BUILD / "Dockerfile")
    shutil.copyfile(ROOT / "config/maps_proxy_test.go", dep / "jshttp/iecho_proxy_test.go")
    shutil.copyfile(ROOT / "config/maps_tls_test.go", dep / "stealth/iecho_tls_test.go")
    print("Patched build prepared. TLS verification remains enabled.")


if __name__ == "__main__":
    main()
