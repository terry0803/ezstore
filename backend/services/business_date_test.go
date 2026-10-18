package services

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
)

func TestTaiwanBusinessDate(t *testing.T) {
	for _, tc := range []struct{ utc, date string }{
		{"2026-10-17T15:59:59Z", "20261017"},
		{"2026-10-17T16:00:00Z", "20261018"},
		{"2026-10-17T23:59:59Z", "20261018"},
		{"2026-12-31T16:00:00Z", "20270101"},
	} {
		now, err := time.Parse(time.RFC3339, tc.utc)
		assert.NoError(t, err)
		assert.Equal(t, tc.date, businessDate(now))
		assert.Equal(t, tc.date, businessDate(now.In(time.FixedZone("other", -7*3600))))
	}
}
