package stealth

import (
    "context"
    "fmt"
    "io"
    "net"
    "net/http"
    "net/http/httptest"
    "testing"
    "strings"

    "github.com/gosom/scrapemate"
)

type iechoProxy struct { url string }
func (p iechoProxy) Next() scrapemate.Proxy { return scrapemate.Proxy{URL: p.url} }

func TestIECHOSelfSignedTLSRejected(t *testing.T) {
    server := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte("must not be trusted")) }))
    defer server.Close()
    // Exercise the proxy branch which previously disabled verification.
    forwarder := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        upstream, err := net.Dial("tcp", server.Listener.Addr().String())
        if err != nil { t.Error(err); return }
        conn, _, err := w.(http.Hijacker).Hijack()
        if err != nil { upstream.Close(); t.Error(err); return }
        _, _ = fmt.Fprint(conn, "HTTP/1.1 200 Connection established\r\n\r\n")
        go func() { defer upstream.Close(); _, _ = io.Copy(upstream, conn) }()
        go func() { defer conn.Close(); _, _ = io.Copy(conn, upstream) }()
    }))
    defer forwarder.Close()
    fetcher := New("firefox", iechoProxy{url: forwarder.URL})
    defer fetcher.Close()
    response := fetcher.Fetch(context.Background(), &scrapemate.Job{URL: server.URL, Method: "GET"})
    if response.Error == nil { t.Fatal("untrusted TLS certificate was accepted") }
    if !strings.Contains(strings.ToLower(response.Error.Error()), "certificate") { t.Fatalf("failed for an unexpected reason: %v", response.Error) }
}
