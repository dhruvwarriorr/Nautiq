// Keep the bounded secret-file contract in sync with API operations/config.go.
package main

import (
	"errors"
	"io"
	"net/url"
	"os"
	"strings"
)

// Secret files are mounted read-only; values never appear in errors or logs.
func LoadSecrets() error {
	for _, key := range []string{"DATABASE_URL", "MINIO_ROOT_USER", "MINIO_ROOT_PASSWORD", "SMTP_USERNAME", "SMTP_PASSWORD"} {
		path := os.Getenv(key + "_FILE")
		if path == "" {
			continue
		}
		if os.Getenv(key) != "" {
			return errors.New("conflicting_secret_configuration")
		}
		f, e := os.Open(path)
		if e != nil {
			return errors.New("secret_file_unavailable")
		}
		info, e := f.Stat()
		if e != nil || !info.Mode().IsRegular() || info.Size() > 16384 {
			f.Close()
			return errors.New("secret_file_invalid")
		}
		b, e := io.ReadAll(io.LimitReader(f, 16385))
		f.Close()
		value := strings.TrimSuffix(strings.TrimSuffix(string(b), "\n"), "\r")
		if e != nil || len(value) == 0 || len(b) > 16384 || strings.ContainsAny(value, "\r\n\x00") {
			return errors.New("secret_file_invalid")
		}
		if e = os.Setenv(key, value); e != nil {
			return errors.New("secret_configuration_failed")
		}
	}
	if os.Getenv("NAUTIQ_DEPLOYMENT") == "production" {
		origin, e := url.Parse(os.Getenv("PRODUCT_WEB_ORIGIN"))
		if e != nil || origin.Scheme != "https" || origin.Host == "" || origin.User != nil || origin.RawQuery != "" || origin.Fragment != "" || origin.Path != "" {
			return errors.New("production_https_origin_required")
		}
		for _, key := range []string{"DATABASE_URL", "MINIO_ROOT_PASSWORD"} {
			v := os.Getenv(key)
			if len(v) < 24 || strings.Contains(v, "nautiq_local") || os.Getenv(key+"_FILE") == "" {
				return errors.New("production_secret_file_required")
			}
		}
	}
	return nil
}
