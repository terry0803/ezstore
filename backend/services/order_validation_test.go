package services

import (
	"errors"
	"testing"

	"github.com/cshliu/ezstore/backend/models"
	"github.com/shopspring/decimal"
)

type quotationLookupStub struct {
	quotation *models.Quotation
	err       error
	calls     []uint
}

func (s *quotationLookupStub) GetByID(id uint) (*models.Quotation, error) {
	s.calls = append(s.calls, id)
	return s.quotation, s.err
}

// Nil repositories prove the order is rejected before any database write.
func TestOrderRejectsNegativePriceBeforeDatabase(t *testing.T) {
	service := &OrderService{}
	input := &OrderCreateInput{CustomerID: 1, Items: []OrderItemInput{{ProductID: 1, Quantity: 2, UnitPrice: decimal.NewFromInt(-1)}}}
	if _, err := service.Create(input); err == nil || err.Error() != "訂單單價不可為負數" {
		t.Fatalf("create: %v", err)
	}
	if _, err := service.Update(1, input); err == nil || err.Error() != "訂單單價不可為負數" {
		t.Fatalf("update: %v", err)
	}
	if err := validateOrderInput(&OrderCreateInput{Items: []OrderItemInput{{Quantity: 1, UnitPrice: decimal.Zero}}}); err != nil {
		t.Fatalf("zero price must stay valid: %v", err)
	}
}

func TestOrderRejectsAnotherCustomersQuotationBeforeWrite(t *testing.T) {
	lookup := &quotationLookupStub{quotation: &models.Quotation{ID: 7, CustomerID: 2}}
	service := &OrderService{QuotationRepo: lookup}
	id := uint(7)
	input := &OrderCreateInput{CustomerID: 1, QuotationID: &id, Items: []OrderItemInput{{ProductID: 1, Quantity: 1, UnitPrice: decimal.NewFromInt(100)}}}
	if _, err := service.Create(input); err == nil || err.Error() != "關聯報價單與訂單必須屬於同一客戶" {
		t.Fatalf("create: %v", err)
	}
	if _, err := service.Update(1, input); err == nil || err.Error() != "關聯報價單與訂單必須屬於同一客戶" {
		t.Fatalf("update: %v", err)
	}
	if len(lookup.calls) != 2 {
		t.Fatalf("expected two lookups, got %v", lookup.calls)
	}
}

func TestOrderQuotationValidation(t *testing.T) {
	id := uint(7)
	lookup := &quotationLookupStub{quotation: &models.Quotation{ID: 7, CustomerID: 1}}
	service := &OrderService{QuotationRepo: lookup}
	if err := service.validateQuotation(&OrderCreateInput{CustomerID: 1, QuotationID: &id}); err != nil {
		t.Fatal(err)
	}
	lookup.err = errors.New("not found")
	if err := service.validateQuotation(&OrderCreateInput{CustomerID: 1, QuotationID: &id}); err == nil || err.Error() != "關聯報價單不存在" {
		t.Fatalf("missing quotation: %v", err)
	}
	if err := service.validateQuotation(&OrderCreateInput{CustomerID: 1}); err != nil {
		t.Fatalf("no quotation link must stay valid: %v", err)
	}
}
