package jshttp

import (
    "io"
    "net/http"
    "net/http/httptest"
    "testing"
)

func TestIECHOUnauthenticatedProxy(t *testing.T) {
    upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if r.Header.Get("Proxy-Authorization") != "" { t.Error("unexpected proxy credentials") }
        _, _ = w.Write([]byte("verified upstream response"))
    }))
    defer upstream.Close()
    p, err := StartAuthProxy(upstream.URL, "", "")
    if err != nil { t.Fatal(err) }
    defer p.Close()
    response, err := p.HTTPClient().Get("http://example.com/probe")
    if err != nil { t.Fatal(err) }
    defer response.Body.Close()
    body, _ := io.ReadAll(response.Body)
    if string(body) != "verified upstream response" { t.Fatalf("unexpected response: %s", body) }
}

func TestIECHOPartialCredentialsRejected(t *testing.T) {
    if _, err := StartAuthProxy("http://localhost:8080", "user", ""); err == nil { t.Fatal("partial credentials accepted") }
}
