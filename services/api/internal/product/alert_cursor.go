package product

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type inboxCursor struct {
	Owner    string     `json:"owner"`
	Snapshot time.Time  `json:"snapshot"`
	Before   *time.Time `json:"before"`
	ID       string     `json:"id"`
	Expires  time.Time  `json:"expires"`
}

func (s *Server) inboxPage(w http.ResponseWriter, r *http.Request, owner string) (int, inboxCursor, bool) {
	now := time.Now().UTC()
	c := inboxCursor{Owner: owner, Snapshot: now, ID: "00000000-0000-0000-0000-000000000000", Expires: now.Add(15 * time.Minute)}
	n := 50
	q := r.URL.Query()
	for k := range q {
		if k != "limit" && k != "after" {
			fail(w, 400, "unknown_query")
			return 0, c, false
		}
	}
	if q.Has("limit") {
		v, e := strconv.Atoi(q.Get("limit"))
		if e != nil || v < 1 || v > 100 {
			fail(w, 400, "invalid_limit")
			return 0, c, false
		}
		n = v
	}
	if q.Has("after") {
		value := q.Get("after")
		parts := strings.Split(value, ".")
		if len(parts) != 2 || len(value) > 2048 {
			fail(w, 400, "invalid_cursor")
			return 0, c, false
		}
		raw, e := base64.RawURLEncoding.DecodeString(parts[0])
		sig, e2 := base64.RawURLEncoding.DecodeString(parts[1])
		mac := hmac.New(sha256.New, s.cursorKey)
		mac.Write(raw)
		if e != nil || e2 != nil || !hmac.Equal(sig, mac.Sum(nil)) || Strict(raw, &c) != nil || c.Owner != owner || c.Before == nil || !identifier(c.ID) || !c.Expires.After(now) || c.Snapshot.After(now.Add(time.Second)) || c.Before.After(c.Snapshot) {
			fail(w, 400, "invalid_or_expired_cursor")
			return 0, c, false
		}
	}
	return n, c, true
}
func (s *Server) signInbox(c inboxCursor) string {
	raw := JSON(c)
	mac := hmac.New(sha256.New, s.cursorKey)
	mac.Write(raw)
	return base64.RawURLEncoding.EncodeToString(raw) + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}
