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
