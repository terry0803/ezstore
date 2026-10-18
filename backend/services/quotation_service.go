package services

import (
	"errors"
	"fmt"
	"time"

	"github.com/cshliu/ezstore/backend/models"
	"github.com/cshliu/ezstore/backend/repositories"
	"github.com/shopspring/decimal"
)

type QuotationCreateInput struct {
	CustomerID    uint                 `json:"customer_id" binding:"required"`
	PricingFactor decimal.Decimal      `json:"pricing_factor" binding:"required"`
	Notes         string               `json:"notes"`
	Items         []QuotationItemInput `json:"items" binding:"required,min=1"`
}

type QuotationItemInput struct {
	ProductID uint `json:"product_id" binding:"required"`
	Quantity  int  `json:"quantity" binding:"required,min=1"`
}

type QuotationService struct {
	Repo         *repositories.QuotationRepository
	CustomerRepo *repositories.CustomerRepository
	ProductRepo  *repositories.ProductRepository
}

func NewQuotationService(repo *repositories.QuotationRepository, customerRepo *repositories.CustomerRepository, productRepo *repositories.ProductRepository) *QuotationService {
	return &QuotationService{Repo: repo, CustomerRepo: customerRepo, ProductRepo: productRepo}
}

func (s *QuotationService) List(page, pageSize int, status string, customerID uint, quotationNumber string) ([]models.Quotation, int64, error) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 20
	}
	return s.Repo.List(page, pageSize, status, customerID, quotationNumber)
}

func (s *QuotationService) GetByID(id uint) (*models.Quotation, error) {
	return s.Repo.GetByID(id)
}

func (s *QuotationService) Create(input *QuotationCreateInput) (*models.Quotation, error) {
	if err := validatePricingFactor(input.PricingFactor); err != nil {
		return nil, err
	}
	input.PricingFactor = input.PricingFactor.Round(4)
	customer, err := s.CustomerRepo.GetByID(input.CustomerID)
	if err != nil {
		return nil, errors.New("客戶不存在")
	}

	quotation := &models.Quotation{
		CustomerID:    input.CustomerID,
		CustomerLevel: customer.Level,
		PricingFactor: input.PricingFactor,
		Status:        "draft",
		Notes:         input.Notes,
	}

	items, err := s.buildItems(input.Items, input.PricingFactor)
	if err != nil {
		return nil, err
	}
	quotation.Items = items

	s.computeTotals(quotation)
	if err := checkProfitRate(quotation); err != nil {
		return nil, err
	}

	if err := createWithRetry(s.generateNumber, func(n string) { quotation.QuotationNumber = n }, func() error { return s.Repo.Create(quotation) }); err != nil {
		return nil, err
	}

	return s.Repo.GetByID(quotation.ID)
}

func (s *QuotationService) Update(id uint, input *QuotationCreateInput) (*models.Quotation, error) {
	if err := validatePricingFactor(input.PricingFactor); err != nil {
		return nil, err
	}
	input.PricingFactor = input.PricingFactor.Round(4)
	existing, err := s.Repo.GetByID(id)
	if err != nil {
		return nil, err
	}

	if existing.Status == "published" {
		return nil, errors.New("已發佈的報價單不可修改")
	}

	customer, err := s.CustomerRepo.GetByID(input.CustomerID)
	if err != nil {
		return nil, errors.New("客戶不存在")
	}

	existing.CustomerID = input.CustomerID
	existing.CustomerLevel = customer.Level
	existing.PricingFactor = input.PricingFactor
	existing.Notes = input.Notes

	items, err := s.buildItems(input.Items, input.PricingFactor)
	if err != nil {
		return nil, err
	}
	existing.Items = items

	s.computeTotals(existing)
	if err := checkProfitRate(existing); err != nil {
		return nil, err
	}

	if err := s.Repo.Update(existing); err != nil {
		return nil, err
	}

	return s.Repo.GetByID(existing.ID)
}

// Match decimal(5,4): reject invalid values before any database mutation.
func validatePricingFactor(value decimal.Decimal) error {
	// Round first, like the agent and MCP do: 9.99994 is stored as 9.9999.
	rounded := value.Round(4)
	if !value.IsPositive() || rounded.GreaterThan(decimal.RequireFromString("9.9999")) || rounded.IsZero() {
		return errors.New("報價因子必須大於 0、最多 9.9999，且小數四位捨入後不可為 0")
	}
	return nil
}

// profit_rate is decimal(5,4) too: a very small factor makes the rate fall
// below -9.9999 and PostgreSQL would answer with a raw overflow error.
func checkProfitRate(q *models.Quotation) error {
	if q.ProfitRate.Round(4).Abs().GreaterThan(decimal.RequireFromString("9.9999")) {
		return errors.New("報價因子太低，利潤率超出可儲存的範圍（-9.9999 到 9.9999）")
	}
	return nil
}

func (s *QuotationService) Publish(id uint) (*models.Quotation, error) {
	quotation, err := s.Repo.GetByID(id)
	if err != nil {
		return nil, err
	}

	if quotation.Status == "published" {
		return nil, errors.New("報價單已經發佈")
	}

	if err := s.Repo.UpdateStatus(id, "published"); err != nil {
		return nil, err
	}

	return s.Repo.GetByID(id)
}

func (s *QuotationService) Delete(id uint) error {
	quotation, err := s.Repo.GetByID(id)
	if err != nil {
		return err
	}

	if quotation.Status == "published" {
		return errors.New("已發佈的報價單不可刪除")
	}

	return s.Repo.Delete(id)
}

func (s *QuotationService) Duplicate(id uint) (*models.Quotation, error) {
	source, err := s.Repo.GetByID(id)
	if err != nil {
		return nil, errors.New("來源報價單不存在")
	}

	// Build items from source items (re-fetch product snapshots for latest data)
	itemInputs := make([]QuotationItemInput, 0, len(source.Items))
	for _, item := range source.Items {
		itemInputs = append(itemInputs, QuotationItemInput{
			ProductID: item.ProductID,
			Quantity:  item.Quantity,
		})
	}

	items, err := s.buildItems(itemInputs, source.PricingFactor)
	if err != nil {
		return nil, err
	}

	notes := formatDuplicateNotes(source.QuotationNumber, source.Notes)

	newQuotation := &models.Quotation{
		CustomerID:    source.CustomerID,
		CustomerLevel: source.CustomerLevel,
		PricingFactor: source.PricingFactor,
		Status:        "draft",
		Notes:         notes,
		Items:         items,
	}

	s.computeTotals(newQuotation)
	if err := checkProfitRate(newQuotation); err != nil {
		return nil, err
	}

	if err := createWithRetry(s.generateNumber, func(n string) { newQuotation.QuotationNumber = n }, func() error { return s.Repo.Create(newQuotation) }); err != nil {
		return nil, err
	}

	return s.Repo.GetByID(newQuotation.ID)
}

func (s *QuotationService) buildItems(inputs []QuotationItemInput, pricingFactor decimal.Decimal) ([]models.QuotationItem, error) {
	items := make([]models.QuotationItem, 0, len(inputs))

	for _, input := range inputs {
		product, err := s.ProductRepo.GetByID(input.ProductID)
		if err != nil {
			return nil, fmt.Errorf("產品 ID %d 不存在", input.ProductID)
		}

		if input.Quantity <= 0 {
			return nil, errors.New("數量必須大於 0")
		}

		// Round the unit once, before quantity multiplication, to match decimal(12,2).
		// Otherwise PostgreSQL rounds unit/subtotal independently and they disagree.
		unitPrice := product.ListPrice.Mul(pricingFactor).Round(2)
		quantity := decimal.NewFromInt(int64(input.Quantity))
		subtotal := unitPrice.Mul(quantity)

		items = append(items, models.QuotationItem{
			ProductID:   input.ProductID,
			ProductName: product.Name,
			ProductCost: product.Cost,
			ListPrice:   product.ListPrice,
			UnitPrice:   unitPrice,
			Quantity:    input.Quantity,
			Subtotal:    subtotal,
		})
	}

	return items, nil
}

func (s *QuotationService) computeTotals(q *models.Quotation) {
	totalPrice := decimal.Zero
	profitAmount := decimal.Zero

	for _, item := range q.Items {
		totalPrice = totalPrice.Add(item.Subtotal)
		profit := item.UnitPrice.Sub(item.ProductCost).Mul(decimal.NewFromInt(int64(item.Quantity)))
		profitAmount = profitAmount.Add(profit)
	}

	q.TotalPrice = totalPrice
	q.ProfitAmount = profitAmount

	if totalPrice.IsZero() {
		q.ProfitRate = decimal.Zero
	} else {
		q.ProfitRate = profitAmount.Div(totalPrice)
	}
}

// generateNumber 產生 QT-YYYYMMDD-NNN；offset 用於撞號重試時往後推序號。
func (s *QuotationService) generateNumber(offset int64) (string, error) {
	count, err := s.Repo.CountToday()
	if err != nil {
		return "", err
	}
	today := time.Now().Format("20060102")
	return fmt.Sprintf("QT-%s-%03d", today, count+1+offset), nil
}

func formatDuplicateNotes(sourceNumber, sourceNotes string) string {
	if sourceNotes != "" {
		return fmt.Sprintf("複製自 %s — %s", sourceNumber, sourceNotes)
	}
	return fmt.Sprintf("複製自 %s", sourceNumber)
}
