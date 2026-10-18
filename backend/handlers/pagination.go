package handlers

import (
	"strconv"

	"github.com/cshliu/ezstore/backend/services"
	"github.com/gin-gonic/gin"
)

func listPagination(c *gin.Context) (int, int) {
	page, err := strconv.Atoi(c.DefaultQuery("page", "1"))
	if err != nil {
		page = 1
	}
	size, err := strconv.Atoi(c.DefaultQuery("page_size", "20"))
	if err != nil {
		size = 20
	}
	return services.NormalizePagination(page, size)
}
