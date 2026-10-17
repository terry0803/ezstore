package services

import (
	"errors"
	"testing"

	"github.com/cshliu/ezstore/backend/models"
	"github.com/shopspring/decimal"
	"github.com/stretchr/testify/assert"
)

// Nil repositories ensure invalid requests are rejected before any database I/O.
func TestQuotationRejectsNonPositiveFactorBeforeDatabase(t *testing.T) {
	service := &QuotationService{}
	for _, factor := range []string{"-1", "0"} {
		input := &QuotationCreateInput{CustomerID: 1, PricingFactor: decimal.RequireFromString(factor), Items: []QuotationItemInput{{ProductID: 1, Quantity: 1}}}
		_, createErr := service.Create(input)
		_, updateErr := service.Update(1, input)
		assert.EqualError(t, createErr, "報價因子必須大於 0")
		assert.EqualError(t, updateErr, "報價因子必須大於 0")
	}
}

func TestOrderRejectsNegativePriceBeforeDatabase(t *testing.T) {
	service := &OrderService{}
	input := &OrderCreateInput{CustomerID: 1, Items: []OrderItemInput{{ProductID: 1, Quantity: 1, UnitPrice: decimal.NewFromInt(-1)}}}
	_, createErr := service.Create(input)
	_, updateErr := service.Update(1, input)
	assert.EqualError(t, createErr, "訂單單價不可為負數")
	assert.EqualError(t, updateErr, "訂單單價不可為負數")
}

func TestOrderZeroPriceIsValid(t *testing.T) {
	assert.NoError(t, validateOrderInput(&OrderCreateInput{Items: []OrderItemInput{{Quantity: 1, UnitPrice: decimal.Zero}}}))
}

type quotationLookupStub struct {
	quotation *models.Quotation
	err       error
	calls     []uint
}

func (s *quotationLookupStub) GetByID(id uint) (*models.Quotation, error) {
	s.calls = append(s.calls, id)
	return s.quotation, s.err
}

func TestOrderRejectsCrossCustomerQuotationBeforeWrite(t *testing.T) {
	lookup := &quotationLookupStub{quotation: &models.Quotation{ID: 7, CustomerID: 2}}
	service := &OrderService{QuotationRepo: lookup}
	id := uint(7)
	input := &OrderCreateInput{CustomerID: 1, QuotationID: &id, Items: []OrderItemInput{{ProductID: 1, Quantity: 1, UnitPrice: decimal.NewFromInt(100)}}}
	_, createErr := service.Create(input)
	_, updateErr := service.Update(1, input)
	assert.EqualError(t, createErr, "關聯報價單與訂單必須屬於同一客戶")
	assert.EqualError(t, updateErr, "關聯報價單與訂單必須屬於同一客戶")
	assert.Equal(t, []uint{7, 7}, lookup.calls)
}

func TestOrderQuotationValidation(t *testing.T) {
	id := uint(7)
	input := &OrderCreateInput{CustomerID: 1, QuotationID: &id}
	lookup := &quotationLookupStub{quotation: &models.Quotation{ID: 7, CustomerID: 1}}
	service := &OrderService{QuotationRepo: lookup}
	assert.NoError(t, service.validateQuotation(input))
	lookup.err = errors.New("not found")
	assert.EqualError(t, service.validateQuotation(input), "關聯報價單不存在")
	assert.NoError(t, service.validateQuotation(&OrderCreateInput{CustomerID: 1}))
	assert.Len(t, lookup.calls, 2)
}

func TestQuotationRejectsFactorAboveColumnLimitBeforeDatabase(t *testing.T) {
	service := &QuotationService{}
	// 9.99995 四捨五入到 4 位是 10.0000，一樣存不進 decimal(5,4)
	for _, factor := range []string{"10", "12.5", "9.99995"} {
		input := &QuotationCreateInput{CustomerID: 1, PricingFactor: decimal.RequireFromString(factor), Items: []QuotationItemInput{{ProductID: 1, Quantity: 1}}}
		_, createErr := service.Create(input)
		_, updateErr := service.Update(1, input)
		assert.EqualError(t, createErr, "報價因子不可超過 9.9999")
		assert.EqualError(t, updateErr, "報價因子不可超過 9.9999")
	}
}

func TestQuotationFactorIsRoundedToStoredPrecision(t *testing.T) {
	cases := map[string]string{"0.77515": "0.7752", "0.77514": "0.7751", "9.99994": "9.9999", "1": "1"}
	for raw, want := range cases {
		input := &QuotationCreateInput{PricingFactor: decimal.RequireFromString(raw), Items: []QuotationItemInput{{ProductID: 1, Quantity: 1}}}
		assert.NoError(t, validateQuotationInput(input))
		assert.True(t, input.PricingFactor.Equal(decimal.RequireFromString(want)), "%s -> %s", raw, input.PricingFactor)
	}
	// 小到四捨五入後變成 0，也算不大於 0
	tiny := &QuotationCreateInput{PricingFactor: decimal.RequireFromString("0.00004"), Items: []QuotationItemInput{{ProductID: 1, Quantity: 1}}}
	assert.EqualError(t, validateQuotationInput(tiny), "報價因子必須大於 0")
}

func TestQuotationProfitRateMustFitColumn(t *testing.T) {
	service := &QuotationService{}
	low := &models.Quotation{Items: []models.QuotationItem{{UnitPrice: decimal.NewFromInt(1), ProductCost: decimal.NewFromInt(100), Quantity: 1, Subtotal: decimal.NewFromInt(1)}}}
	service.computeTotals(low)
	assert.EqualError(t, checkProfitRate(low), "報價因子太低，利潤率超出可儲存的範圍（-9.9999 到 9.9999）")
	normal := &models.Quotation{Items: []models.QuotationItem{{UnitPrice: decimal.NewFromInt(80), ProductCost: decimal.NewFromInt(40), Quantity: 2, Subtotal: decimal.NewFromInt(160)}}}
	service.computeTotals(normal)
	assert.NoError(t, checkProfitRate(normal))
}
