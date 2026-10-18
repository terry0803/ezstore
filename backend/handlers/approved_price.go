package handlers

import (
	"errors"
	"github.com/cshliu/ezstore/backend/middleware"
	"github.com/cshliu/ezstore/backend/services"
	"github.com/gin-gonic/gin"
	"net/http"
	"strconv"
)

// ApprovedPriceCopy is the advisor's atomic version-conditional copy endpoint.
func (h *QuotationHandler) ApprovedPriceCopy(c *gin.Context) {
	id, err := strconv.ParseUint(c.Param("id"), 10, 32)
	if err != nil {
		middleware.ErrorResponse(c, 400, "INVALID_ID", "無效的報價單 ID")
		return
	}
	var input services.ApprovedPriceInput
	if err := c.ShouldBindJSON(&input); err != nil {
		middleware.ErrorResponse(c, 400, "VALIDATION_ERROR", "核准資料格式錯誤，沒有建立副本")
		return
	}
	q, err := h.Service.ApprovedPriceCopy(uint(id), &input)
	if err != nil {
		status, code := http.StatusBadRequest, "VALIDATION_ERROR"
		if errors.Is(err, services.ErrApprovalChanged) {
			status, code = http.StatusConflict, "APPROVAL_CHANGED"
		}
		middleware.ErrorResponse(c, status, code, err.Error())
		return
	}
	c.JSON(http.StatusCreated, q)
}
