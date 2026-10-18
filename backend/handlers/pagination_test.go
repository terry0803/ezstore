package handlers

import (
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
)

func TestListPagination(t *testing.T) {
	gin.SetMode(gin.TestMode)
	for _, tc := range []struct {
		query      string
		page, size int
	}{
		{"", 1, 20},
		{"?page=0&page_size=999", 1, 20},
		{"?page=-5&page_size=0", 1, 20},
		{"?page=abc&page_size=xyz", 1, 20},
		{"?page=2&page_size=100", 2, 100},
		{"?page=999999999999999999999999999999&page_size=30", 1, 30},
		{"?page=9223372036854775807&page_size=100", 1, 100},
	} {
		c, _ := gin.CreateTestContext(httptest.NewRecorder())
		c.Request = httptest.NewRequest("GET", "/"+tc.query, nil)
		page, size := listPagination(c)
		assert.Equal(t, tc.page, page, tc.query)
		assert.Equal(t, tc.size, size, tc.query)
	}
}
