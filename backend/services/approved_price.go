package services

import (
	"errors"
	"sort"

	"github.com/cshliu/ezstore/backend/models"
	"github.com/shopspring/decimal"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

// This is a version precondition, not authentication or a manager signature.
// The advisor supplies the snapshot and the result of its attested calculation.
type ApprovedPriceInput struct {
	Source models.Quotation `json:"source"`
	Target decimal.Decimal  `json:"target_total"`
	Factor decimal.Decimal  `json:"factor"`
	Total  decimal.Decimal  `json:"total"`
	Profit decimal.Decimal  `json:"profit"`
}

var ErrApprovalChanged = errors.New("核准版本或計算結果已變更，沒有建立副本；請重新試算並取得核准")

func sameApprovedSource(a, b *models.Quotation) bool {
	if a.ID != b.ID || b.UpdatedAt.IsZero() || !a.UpdatedAt.Equal(b.UpdatedAt) ||
		a.QuotationNumber != b.QuotationNumber || a.CustomerID != b.CustomerID ||
		a.CustomerLevel != b.CustomerLevel || a.Status != b.Status || a.Notes != b.Notes ||
		!a.PricingFactor.Equal(b.PricingFactor) || !a.TotalPrice.Equal(b.TotalPrice) ||
		!a.ProfitAmount.Equal(b.ProfitAmount) || !a.ProfitRate.Equal(b.ProfitRate) ||
		len(a.Items) == 0 || len(a.Items) != len(b.Items) {
		return false
	}
	items := make(map[uint]models.QuotationItem, len(b.Items))
	for _, i := range b.Items {
		items[i.ID] = i
	}
	if len(items) != len(b.Items) {
		return false
	}
	for _, x := range a.Items {
		y, ok := items[x.ID]
		if !ok || x.ProductID != y.ProductID || x.Quantity != y.Quantity ||
			x.ProductName != y.ProductName || !x.ProductCost.Equal(y.ProductCost) ||
			!x.ListPrice.Equal(y.ListPrice) || !x.UnitPrice.Equal(y.UnitPrice) || !x.Subtotal.Equal(y.Subtotal) {
			return false
		}
	}
	return true
}

// ApprovedPriceCopy commits only the final approved draft. Source, customer and
// products stay locked from validation through insertion. Never call Duplicate
// followed by Update here: that would reopen the approval/write race.
func (s *QuotationService) ApprovedPriceCopy(id uint, input *ApprovedPriceInput) (*models.Quotation, error) {
	if input.Source.ID != id || !input.Target.IsPositive() ||
		input.Factor.LessThan(decimal.RequireFromString("0.01")) || input.Factor.GreaterThan(decimal.NewFromInt(5)) ||
		!input.Factor.Equal(input.Factor.Round(4)) {
		return nil, ErrApprovalChanged
	}
	var result *models.Quotation
	var number string
	err := createWithRetry(s.generateNumber, func(n string) { number = n }, func() error {
		// A unique-number conflict aborts PostgreSQL's transaction. Retry the
		// entire transaction, rechecking the SAME approval snapshot each time.
		return s.Repo.DB.Transaction(func(tx *gorm.DB) error {
			var source models.Quotation
			if err := tx.Clauses(clause.Locking{Strength: "UPDATE"}).First(&source, id).Error; err != nil {
				return ErrApprovalChanged
			}
			if err := tx.Where("quotation_id = ?", id).Find(&source.Items).Error; err != nil {
				return err
			}
			if !sameApprovedSource(&source, &input.Source) {
				return ErrApprovalChanged
			}
			var customer models.Customer
			if err := tx.Clauses(clause.Locking{Strength: "SHARE"}).First(&customer, source.CustomerID).Error; err != nil {
				return ErrApprovalChanged
			}
			if customer.Level != source.CustomerLevel {
				return ErrApprovalChanged
			}
			ids := make([]uint, 0, len(source.Items))
			seen := map[uint]bool{}
			for _, item := range source.Items {
				if !seen[item.ProductID] {
					ids = append(ids, item.ProductID)
					seen[item.ProductID] = true
				}
			}
			sort.Slice(ids, func(i, j int) bool { return ids[i] < ids[j] })
			products := map[uint]models.Product{}
			for _, pid := range ids {
				var product models.Product
				if err := tx.Clauses(clause.Locking{Strength: "SHARE"}).First(&product, pid).Error; err != nil {
					return ErrApprovalChanged
				}
				products[pid] = product
			}
			q := &models.Quotation{QuotationNumber: number, CustomerID: source.CustomerID,
				CustomerLevel: source.CustomerLevel, PricingFactor: input.Factor, Status: "draft",
				Notes: formatDuplicateNotes(source.QuotationNumber, source.Notes)}
			for _, item := range source.Items {
				p := products[item.ProductID]
				if item.Quantity <= 0 || !p.Cost.Equal(item.ProductCost) || !p.ListPrice.Equal(item.ListPrice) {
					return ErrApprovalChanged
				}
				unit := p.ListPrice.Mul(input.Factor).Round(2)
				q.Items = append(q.Items, models.QuotationItem{ProductID: p.ID, ProductName: p.Name,
					ProductCost: p.Cost, ListPrice: p.ListPrice, Quantity: item.Quantity, UnitPrice: unit,
					Subtotal: unit.Mul(decimal.NewFromInt(int64(item.Quantity)))})
			}
			s.computeTotals(q)
			if !q.TotalPrice.Equal(input.Total) || !q.ProfitAmount.Equal(input.Profit) {
				return ErrApprovalChanged
			}
			if err := checkProfitRate(q); err != nil {
				return err
			}
			if err := tx.Omit("Customer").Create(q).Error; err != nil {
				return err
			}
			// Read in the same transaction; failed reload must also roll back.
			var saved models.Quotation
			if err := tx.Preload("Customer").Preload("Items").First(&saved, q.ID).Error; err != nil {
				return err
			}
			result = &saved
			return nil
		})
	})
	if err != nil {
		return nil, err
	}
	return result, nil
}
