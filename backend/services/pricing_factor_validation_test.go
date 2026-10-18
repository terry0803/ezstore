package services

import (
	"testing"

	"github.com/cshliu/ezstore/backend/models"
	"github.com/shopspring/decimal"
)

func TestRejectInvalidPricingFactorBeforeAnyDatabaseAccess(t *testing.T) {
	service := &QuotationService{}
	for _, value := range []string{"-1", "0", "0.00001", "9.99995", "10", "999999999999"} {
		t.Run(value, func(t *testing.T) {
			input := &QuotationCreateInput{PricingFactor: decimal.RequireFromString(value)}
			if _, err := service.Create(input); err == nil {
				t.Fatal("Create accepted invalid factor")
			}
			if _, err := service.Update(1, input); err == nil {
				t.Fatal("Update accepted invalid factor")
			}
		})
	}
}

func TestValidPricingFactorBoundaries(t *testing.T) {
	for _, value := range []string{"0.0001", "0.9", "1", "9.9999", "9.99994"} {
		if err := validatePricingFactor(decimal.RequireFromString(value)); err != nil {
			t.Errorf("%s: %v", value, err)
		}
	}
}

func TestProfitRateMustFitColumn(t *testing.T) {
	service := &QuotationService{}
	low := &models.Quotation{Items: []models.QuotationItem{{UnitPrice: decimal.NewFromInt(1), ProductCost: decimal.NewFromInt(100), Quantity: 1, Subtotal: decimal.NewFromInt(1)}}}
	service.computeTotals(low)
	if checkProfitRate(low) == nil {
		t.Fatal("profit rate -99 must be rejected")
	}
	normal := &models.Quotation{Items: []models.QuotationItem{{UnitPrice: decimal.NewFromInt(80), ProductCost: decimal.NewFromInt(40), Quantity: 2, Subtotal: decimal.NewFromInt(160)}}}
	service.computeTotals(normal)
	if err := checkProfitRate(normal); err != nil {
		t.Fatal(err)
	}
}
