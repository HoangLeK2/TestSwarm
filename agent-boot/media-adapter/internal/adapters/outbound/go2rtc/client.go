package go2rtc

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"devicefarm/media-adapter/internal/domain/stream"
)

type Config struct {
	BaseURL        string
	RTSPTemplate   string
	RequestTimeout time.Duration
}

type Client struct {
	cfg    Config
	client *http.Client
}

type SessionDescription struct {
	Type string `json:"type"`
	SDP  string `json:"sdp"`
}

type HTTPError struct {
	StatusCode int
	Message    string
}

func (e HTTPError) Error() string {
	return fmt.Sprintf("go2rtc returned %d: %s", e.StatusCode, e.Message)
}

func New(cfg Config) *Client {
	if cfg.BaseURL == "" {
		cfg.BaseURL = "http://host.docker.internal:1984"
	}
	if cfg.RTSPTemplate == "" {
		cfg.RTSPTemplate = "rtsp://host.docker.internal:8556/{stream_raw}"
	}
	if cfg.RequestTimeout <= 0 {
		cfg.RequestTimeout = 900 * time.Millisecond
	}
	transport := http.DefaultTransport.(*http.Transport).Clone()
	transport.MaxIdleConns = 512
	transport.MaxIdleConnsPerHost = 256
	transport.IdleConnTimeout = 30 * time.Second
	return &Client{
		cfg: cfg,
		client: &http.Client{
			Timeout:   cfg.RequestTimeout,
			Transport: transport,
		},
	}
}

func ConfigFromEnv() Config {
	timeout := envInt("MEDIA_ADAPTER_GO2RTC_TIMEOUT_MS", 900)
	return Config{
		BaseURL: strings.TrimRight(envDefault("MEDIA_ADAPTER_GO2RTC_URL", envDefault("GO2RTC_URL", "http://host.docker.internal:1984")), "/"),
		RTSPTemplate: envDefault(
			"MEDIA_ADAPTER_GO2RTC_RTSP_SOURCE_TEMPLATE",
			envDefault("MEDIA_ADAPTER_RTSP_URL_TEMPLATE", "rtsp://host.docker.internal:8556/{stream_raw}"),
		),
		RequestTimeout: time.Duration(timeout) * time.Millisecond,
	}
}

func (c *Client) StreamName(serial string) string {
	return stream.StreamName(serial)
}

func (c *Client) StreamSource(serial string) string {
	name := c.StreamName(serial)
	return strings.NewReplacer(
		"{serial}", url.PathEscape(serial),
		"{stream}", url.PathEscape(name),
		"{stream_raw}", name,
	).Replace(c.cfg.RTSPTemplate)
}

func (c *Client) RegisterStream(ctx context.Context, serial string) error {
	endpoint, err := url.Parse(c.cfg.BaseURL + "/api/streams")
	if err != nil {
		return err
	}
	query := endpoint.Query()
	query.Set("name", c.StreamName(serial))
	query.Set("src", c.StreamSource(serial))
	endpoint.RawQuery = query.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodPut, endpoint.String(), nil)
	if err != nil {
		return err
	}
	res, err := c.client.Do(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode >= 400 {
		body, _ := io.ReadAll(io.LimitReader(res.Body, 4096))
		return HTTPError{StatusCode: res.StatusCode, Message: strings.TrimSpace(string(body))}
	}
	return nil
}

func (c *Client) Answer(ctx context.Context, serial string, offer SessionDescription) (SessionDescription, error) {
	if err := c.RegisterStream(ctx, serial); err != nil {
		return SessionDescription{}, err
	}
	payload, err := json.Marshal(offer)
	if err != nil {
		return SessionDescription{}, err
	}
	endpoint, err := url.Parse(c.cfg.BaseURL + "/api/webrtc")
	if err != nil {
		return SessionDescription{}, err
	}
	query := endpoint.Query()
	query.Set("src", c.StreamName(serial))
	endpoint.RawQuery = query.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint.String(), bytes.NewReader(payload))
	if err != nil {
		return SessionDescription{}, err
	}
	req.Header.Set("Content-Type", "application/json")
	res, err := c.client.Do(req)
	if err != nil {
		return SessionDescription{}, err
	}
	defer res.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(res.Body, 1<<20))
	if res.StatusCode >= 400 {
		return SessionDescription{}, HTTPError{StatusCode: res.StatusCode, Message: strings.TrimSpace(string(body))}
	}
	var answer SessionDescription
	if err := json.Unmarshal(body, &answer); err != nil {
		answer = SessionDescription{Type: "answer", SDP: strings.TrimSpace(string(body))}
	}
	if answer.SDP == "" {
		return SessionDescription{}, fmt.Errorf("go2rtc returned empty WebRTC answer")
	}
	if answer.Type == "" {
		answer.Type = "answer"
	}
	return answer, nil
}

func envDefault(name string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return fallback
	}
	return value
}

func envInt(name string, fallback int) int {
	value := strings.TrimSpace(os.Getenv(name))
	if value == "" {
		return fallback
	}
	var parsed int
	if _, err := fmt.Sscanf(value, "%d", &parsed); err != nil || parsed <= 0 {
		return fallback
	}
	return parsed
}
