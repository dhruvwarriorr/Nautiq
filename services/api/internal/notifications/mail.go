package notifications

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net"
	"net/mail"
	"net/smtp"
	"os"
	"strconv"
	"strings"
	"time"
)

type Mailer interface {
	Send(context.Context, string, string, string, string) error
}
type SMTP struct{ Host, Port, Mode, From, User, Password string }

func Address(value string) (string, error) {
	if len(value) > 254 || len(value) < 3 || strings.ContainsAny(value, "\r\n\t <>(),:;\\\"") {
		return "", errors.New("invalid_email")
	}
	for _, c := range value {
		if c < 33 || c > 126 {
			return "", errors.New("ascii_email_required")
		}
	}
	a, e := mail.ParseAddress(value)
	if e != nil || a.Name != "" || a.Address != value {
		return "", errors.New("invalid_email")
	}
	parts := strings.Split(value, "@")
	if len(parts) != 2 || len(parts[0]) > 64 || !strings.Contains(parts[1], ".") || strings.Contains(parts[0], "..") || strings.HasPrefix(parts[0], ".") || strings.HasSuffix(parts[0], ".") {
		return "", errors.New("invalid_email")
	}
	for _, label := range strings.Split(parts[1], ".") {
		if len(label) == 0 || len(label) > 63 || strings.HasPrefix(label, "-") || strings.HasSuffix(label, "-") {
			return "", errors.New("invalid_email")
		}
		for _, c := range label {
			if !(c >= 'a' && c <= 'z' || c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '-') {
				return "", errors.New("invalid_email")
			}
		}
	}
	return parts[0] + "@" + strings.ToLower(parts[1]), nil
}
func SMTPFromEnv() (*SMTP, error) {
	host := os.Getenv("SMTP_HOST")
	if host == "" {
		return nil, nil
	}
	s := &SMTP{Host: host, Port: os.Getenv("SMTP_PORT"), Mode: os.Getenv("SMTP_MODE"), From: os.Getenv("SMTP_FROM"), User: os.Getenv("SMTP_USERNAME"), Password: os.Getenv("SMTP_PASSWORD")}
	if s.Mode == "" {
		s.Mode = "starttls"
	}
	if s.Port == "" {
		s.Port = "587"
	}
	_, e := s.Validate()
	return s, e
}
func (s *SMTP) Validate() (string, error) {
	from, e := Address(s.From)
	port, p := strconv.Atoi(s.Port)
	if e != nil || p != nil || port < 1 || port > 65535 || strings.ContainsAny(s.Host, "\r\n /@") || s.Host == "" {
		return "", errors.New("invalid_smtp_configuration")
	}
	if s.Mode != "starttls" && s.Mode != "tls" && s.Mode != "loopback" {
		return "", errors.New("smtp_tls_required")
	}
	ip := net.ParseIP(s.Host)
	if s.Mode == "loopback" && (ip == nil || !ip.IsLoopback() || s.User != "" || s.Password != "") {
		return "", errors.New("plaintext_smtp_requires_literal_loopback_without_auth")
	}
	if (s.User == "") != (s.Password == "") {
		return "", errors.New("smtp_auth_pair_required")
	}
	return from, nil
}
func (s *SMTP) Send(ctx context.Context, to, id, subject, body string) error {
	from, e := s.Validate()
	if e != nil {
		return e
	}
	to, e = Address(to)
	if e != nil {
		return e
	}
	if strings.ContainsAny(id+subject, "\r\n") || len(subject) > 120 || len(body) > 4096 {
		return errors.New("mail_budget")
	}
	dial := net.Dialer{Timeout: 5 * time.Second}
	conn, e := dial.DialContext(ctx, "tcp", net.JoinHostPort(s.Host, s.Port))
	if e != nil {
		return errors.New("smtp_connect_failed")
	}
	defer conn.Close()
	deadline := time.Now().Add(8 * time.Second)
	if d, ok := ctx.Deadline(); ok && d.Before(deadline) {
		deadline = d
	}
	_ = conn.SetDeadline(deadline)
	config := &tls.Config{ServerName: s.Host, MinVersion: tls.VersionTLS12}
	if s.Mode == "tls" {
		secure := tls.Client(conn, config)
		if e = secure.HandshakeContext(ctx); e != nil {
			return errors.New("smtp_tls_failed")
		}
		conn = secure
	}
	client, e := smtp.NewClient(conn, s.Host)
	if e != nil {
		return errors.New("smtp_greeting_failed")
	}
	defer client.Close()
	if s.Mode == "starttls" {
		if ok, _ := client.Extension("STARTTLS"); !ok {
			return errors.New("smtp_tls_unavailable")
		}
		if e = client.StartTLS(config); e != nil {
			return errors.New("smtp_tls_failed")
		}
	}
	if s.User != "" {
		if e = client.Auth(smtp.PlainAuth("", s.User, s.Password, s.Host)); e != nil {
			return errors.New("smtp_auth_failed")
		}
	}
	if e = client.Mail(from); e != nil {
		return errors.New("smtp_sender_refused")
	}
	if e = client.Rcpt(to); e != nil {
		return errors.New("smtp_recipient_refused")
	}
	out, e := client.Data()
	if e != nil {
		return errors.New("smtp_data_refused")
	}
	message := fmt.Sprintf("From: %s\r\nTo: %s\r\nSubject: %s\r\nMessage-ID: <%s@%s>\r\nDate: %s\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n%s\r\n", from, to, subject, id, strings.Split(from, "@")[1], time.Now().UTC().Format(time.RFC1123Z), strings.ReplaceAll(strings.ReplaceAll(body, "\r\n", "\n"), "\n", "\r\n"))
	if _, e = out.Write([]byte(message)); e != nil {
		return errors.New("smtp_write_failed")
	}
	if e = out.Close(); e != nil {
		return errors.New("smtp_acceptance_unknown")
	}
	// DATA acceptance is the receipt; QUIT failure must not cause another attempt.
	_ = client.Quit()
	return nil
}
